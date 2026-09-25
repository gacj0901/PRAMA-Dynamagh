"""Sequential explicit fan-out with a durable at-most-once payment claim.

PostgreSQL serializes claims across tasks and deliveries. A network outcome
that cannot be established holds its maximum and is never paid again.
"""
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import urlopen

from app.domain.mandates import AcquisitionTask, TelegraphCall, Mandate, MandateStatus, PublicManualSpendReservation, UsageEvent, AutonomyRun, AgentIdentity, AutonomyPolicy
from app.domain.state_machine import transition_mandate
from app.persistence.database import SessionLocal
from app.users import credit as user_credit
from app.public_safety import MAX_SINGLE_ACQUISITION_USDC, m2m_max_workflow_usdc, public_max_mandate_usdc, verify_spend_reservation, settle_spend, release_spend_reservation
from app.authority.recovery import G13_REVIEW_RECOVERY_POLICY_VERSION
from app.authority.failure_episode import (
    FAILURE_EPISODE_ACCESS_MECHANISM,
    FAILURE_EPISODE_PROVIDER,
    FAILURE_EPISODE_SCHEMA_VERSION,
    failure_episode_id,
    is_external_dependency_failure,
)
from app.acquisition.gateway import AcquisitionAdapterError
from app.acquisition.provider import configured_acquisition_adapter
from app.autonomy.service import finalize_http_run
from app.epistemic.contracts import canonical_hash

logger = logging.getLogger(__name__)
now = lambda: datetime.now(timezone.utc)
GATEWAY_REQUEST_TIMEOUT_SECONDS = 120
NO_PAYMENT_GATEWAY_FAILURE = "PAYMENT_REQUIRED"


def maximum(mandate, session=None):
    if mandate.origin == "USER": return min(MAX_SINGLE_ACQUISITION_USDC, public_max_mandate_usdc())
    if mandate.origin == "M2M": return m2m_max_workflow_usdc()
    if mandate.origin == "AUTONOMOUS":
        if session is not None:
            from app.authority.delegated import resolve_profile
            profile = resolve_profile(session, mandate.agent_identity_id)
        else:
            profile = None
        if profile is not None:
            if profile.unlimited_budget: return m2m_max_workflow_usdc()
            if profile.economic_budget is not None: return Decimal(profile.economic_budget)
        return m2m_max_workflow_usdc()
    return public_max_mandate_usdc()


# Complete taxonomy of codes the Gateway can return in an /ask error body
# (gateway/src/server.ts + telegraph.ts) plus this worker's own failure codes.
# Anything outside this set that the Gateway emits is preserved verbatim as
# failure_code ("GATEWAY_UNCLASSIFIED_RESPONSE" fallback keeps the raw body).
GATEWAY_FAILURE_CODES = {
    "PAYMENT_REQUIRED", "PAYMENT_FAILED", "PAYMENT_BUDGET_INVALID",
    "PAYMENT_NETWORK_UNSUPPORTED", "PAYMENT_ASSET_MISMATCH",
    "PAYMENT_BUDGET_EXCEEDED", "TELEGRAPH_REQUEST_FAILED",
    "TELEGRAPH_UNAVAILABLE", "SIGNAL_VERIFICATION_FAILED",
}
WORKER_FAILURE_CODES = {
    "WORKFLOW_BUDGET_EXCEEDED", "BUDGET_EXHAUSTED", "ACQUISITION_QUERY_INVALID",
    "TELEGRAPH_INVALID_RESPONSE", "PAYMENT_COST_UNAVAILABLE",
    "SINGLE_ACQUISITION_BUDGET_EXCEEDED", "PUBLIC_SPEND_AUTHORIZATION_INVALID",
    "PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE", "PUBLIC_SPEND_SETTLEMENT_INVALID",
    "AUTONOMY_RUN_MISSING", "AUTHORITY_COMPOSITION_RESTRICTED", "G13_HALT",
    "G13_REVIEW", "G13_THROTTLE_CONSTRAINTS_REQUIRED", "AUTHORITY_PROFILE_MISSING",
    "AUTHORITY_PROFILE_AMBIGUOUS", "AUTHORITY_HASH_UNVERIFIED",
    "FULL_AUTONOMY_DISABLED", "AMBIGUOUS_AGENT_AUTHORITY", "AGENT_AUTONOMY_HALTED",
    "AGENT_AUTONOMY_REVIEW_REQUIRED", "EXECUTION_PERMIT_INVALID",
    "EXECUTION_PERMIT_EXPIRED", "EXECUTION_PERMIT_CONSUMED",
    "EXECUTION_PERMIT_MISSING", "EXECUTION_PERMIT_ALREADY_CONSUMED",
    "EXECUTION_PERMIT_PAYLOAD_MISMATCH", "EXECUTION_PERMIT_TARGET_MISMATCH",
    "EXECUTION_PERMIT_ECONOMIC_MISMATCH", "EXECUTION_PERMIT_ACTION_MISMATCH",
    "EXECUTION_PERMIT_AUTHORITY_STALE", "EXECUTION_PERMIT_PROFILE_INVALID",
    "EXECUTION_PERMIT_G12_INVALID", "EXECUTION_PERMIT_G13_INVALID",
    "GATEWAY_UNAVAILABLE", "GATEWAY_UNCLASSIFIED_RESPONSE",
}
KNOWN_FAILURE_CODES = GATEWAY_FAILURE_CODES | WORKER_FAILURE_CODES


def uncertain_hold(session, mandate_id):
    events = session.query(UsageEvent).filter_by(mandate_id=mandate_id, event_type="ACQUISITION_PAYMENT_UNCERTAIN").all()
    reconciled = {
        event.acquisition_id
        for event in session.query(UsageEvent).filter_by(
            mandate_id=mandate_id,
            event_type="ACQUISITION_PAYMENT_RECONCILED",
        ).all()
    }
    return sum(
        (Decimal(event.metadata_["held_budget_usdc"]) for event in events if event.acquisition_id not in reconciled),
        Decimal("0"),
    )


def _adapter_target_material(adapter):
    """Return secret-free, provider-neutral adapter/target identity material."""
    adapter_kind = f"{type(adapter).__module__}.{type(adapter).__qualname__}"
    target_config = {"adapter_kind": adapter_kind}
    if hasattr(adapter, "base_url"):
        target_config.update(target_kind="http_base_url", target=getattr(adapter, "base_url"))
    elif hasattr(adapter, "command"):
        environment = getattr(adapter, "environment", {}) or {}
        target_config.update(
            target_kind="mcp_stdio",
            command=getattr(adapter, "command"),
            engine=environment.get("TELEGRAPH_ENGINE_URL"),
        )
    elif hasattr(adapter, "execution_target"):
        target_config.update(target_kind="declared", target=getattr(adapter, "execution_target"))
    else:
        target_config.update(target_kind="adapter_identity_only")
    return {
        "provider": getattr(adapter, "provider", None),
        "access_mechanism": getattr(adapter, "access_mechanism", None),
        "adapter_kind": adapter_kind,
        # Store only the fingerprint: configured targets/commands can contain
        # private routing or credential-bearing values.
        "execution_target_fingerprint": canonical_hash(target_config),
    }


def _reservation_action_material(reservation):
    return {
        "mandate_id": reservation.mandate_id,
        "spend_date": reservation.spend_date.isoformat(),
        "reserved_usdc": Decimal(reservation.reserved_usdc),
        "status": reservation.status,
        "origin": reservation.origin,
    }


def _build_action_material(*, mandate, task, adapter, amount, reservation):
    from app.authority.delegated import build_execution_action_material
    return build_execution_action_material(
        mandate_id=mandate.mandate_id,
        agent_identity_id=mandate.agent_identity_id,
        action_id=task.acquisition_id,
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        query=task.query,
        requested_intent=task.requested_intent,
        causal_request_id=mandate.mandate_id,
        amount=Decimal(amount),
        adapter_target=_adapter_target_material(adapter),
        reservation=_reservation_action_material(reservation),
    )


def _validate_fresh_autonomous_authority(
    session, *, permit, mandate_id, acquisition_id, run, adapter,
    action_material, budget, throttle_ok,
):
    """Re-read revocable authority and exact action while permit row is locked."""
    from app.authority.delegated import (
        _allowed,
        g12_check,
        resolve_profile,
    )
    from app.authority.runtime import evaluate_current_g13, run_pre_next_action_authority_check

    mandate = session.query(Mandate).populate_existing().filter_by(mandate_id=mandate_id).with_for_update().one_or_none()
    task = session.query(AcquisitionTask).populate_existing().filter_by(acquisition_id=acquisition_id).with_for_update().one_or_none()
    if (
        mandate is None or task is None or task.mandate_id != mandate_id
        or mandate.origin != "AUTONOMOUS"
        or mandate.status != "ACQUIRING"
        or task.status != "RUNNING"
        or mandate.agent_identity_id != permit.agent_identity_id
    ):
        raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")
    identity = session.query(AgentIdentity).populate_existing().filter_by(agent_id=mandate.agent_identity_id).with_for_update().one_or_none()
    if identity is None or identity.status != "ACTIVE":
        raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")
    if identity.autonomy_state == "HALTED":
        raise ValueError("EXECUTION_PERMIT_G13_INVALID")
    if identity.autonomy_state != (permit.constraints or {}).get("agent_autonomy_state"):
        raise ValueError("EXECUTION_PERMIT_G13_INVALID")
    from app.authority.delegated import full_autonomy_enabled
    if not full_autonomy_enabled(identity.agent_id):
        raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")

    reservation = session.query(PublicManualSpendReservation).filter_by(
        mandate_id=mandate_id,
    ).populate_existing().with_for_update().one_or_none()
    if (
        reservation is None or reservation.status != "RESERVED"
        or reservation.origin != "AUTONOMOUS"
        or reservation.reserved_usdc <= 0
    ):
        raise ValueError("EXECUTION_PERMIT_G12_INVALID")
    current_action = _build_action_material(
        mandate=mandate, task=task, adapter=adapter,
        amount=budget, reservation=reservation,
    )
    from app.authority.delegated import _validate_action_match
    _validate_action_match(action_material, current_action)

    try:
        profile = resolve_profile(session, identity.agent_id)
    except ValueError as error:
        raise ValueError("EXECUTION_PERMIT_PROFILE_INVALID") from error
    if (
        profile.authority_profile_id != permit.authority_profile_id
        or profile.status != "ACTIVE"
        or not _allowed(profile, permit.action_kind, task.requested_intent)
    ):
        raise ValueError("EXECUTION_PERMIT_PROFILE_INVALID")
    # Profile lifecycle mutations take the same row lock in profiles.py.
    # Lock it now and resolve once more so a concurrent revoke/version switch
    # cannot slip between freshness resolution and permit consumption.
    locked_profile = session.query(type(profile)).filter_by(
        authority_profile_id=profile.authority_profile_id,
    ).with_for_update().one_or_none()
    if locked_profile is None:
        raise ValueError("EXECUTION_PERMIT_PROFILE_INVALID")
    try:
        profile = resolve_profile(session, identity.agent_id)
    except ValueError as error:
        raise ValueError("EXECUTION_PERMIT_PROFILE_INVALID") from error
    if profile.authority_profile_id != permit.authority_profile_id:
        raise ValueError("EXECUTION_PERMIT_PROFILE_INVALID")

    try:
        cap = maximum(mandate, session)
        reservation = verify_spend_reservation(session, mandate_id, cap, "AUTONOMOUS")
        available = reservation.reserved_usdc - uncertain_hold(session, mandate_id)
        allowed, _reason = g12_check(profile, Decimal(budget), reservation_verified=True)
        if (
            not allowed or reservation.reserved_usdc > cap
            or Decimal(budget) <= 0 or Decimal(budget) > available
        ):
            raise ValueError("EXECUTION_PERMIT_G12_INVALID")
        user_credit.verify_reserved(session, mandate, Decimal(budget))
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("EXECUTION_PERMIT_G12_INVALID") from error

    try:
        longitudinal = evaluate_current_g13(session, identity.agent_id)
        current_throttle_ok = throttle_ok
        if longitudinal.result == "THROTTLE":
            ceiling = cap if profile.unlimited_budget else Decimal(profile.per_action_budget or profile.economic_budget or cap)
            configured = (profile.human_review_thresholds or {}).get("throttle_max_usdc")
            limit = Decimal(str(configured)) if configured is not None else ceiling / Decimal("2")
            if longitudinal.result_core.get("operator_recovery_canary"):
                recovery = longitudinal.input_core.get("operator_recovery") or {}
                limit = min(ceiling, Decimal(str(recovery.get("canary_budget_usdc", "0"))))
            current_throttle_ok = Decimal(budget) <= limit
        stored_constraints = permit.constraints or {}
        recovery_probe = bool(stored_constraints.get("recovery_probe_authorized")) and bool(
            longitudinal.result_core.get("recovery_probe_authorized")
        )
        bootstrap_authorized = bool(stored_constraints.get("bootstrap_authorized"))
        if (
            longitudinal.result == "REVIEW"
            and not recovery_probe
            and not bootstrap_authorized
            and not stored_constraints.get("recovery_observation_permitted")
        ):
            raise ValueError("EXECUTION_PERMIT_G13_INVALID")
        bootstrap_grant = None
        if bootstrap_authorized:
            from app.authority.bootstrap import bootstrap_eligibility
            policy = session.get(AutonomyPolicy, run.policy_id)
            eligible, _reason, bootstrap_grant = bootstrap_eligibility(
                session, identity=identity, policy=policy, profile=profile,
                g13_core=longitudinal, action_kind=permit.action_kind,
                amount=Decimal(budget),
            )
            if not eligible or bootstrap_grant is None or bootstrap_grant.bootstrap_authority_id != stored_constraints.get("bootstrap_authority_id"):
                raise ValueError("EXECUTION_PERMIT_G13_INVALID")
        checkpoint = run_pre_next_action_authority_check(
            session,
            mandate=mandate,
            acquisition=task,
            run=run,
            g12_authorized=True,
            g12_reservation=reservation,
            current_runtime_action="CONTINUE_TO_GATEWAY",
            throttled_constraints_satisfied=current_throttle_ok,
            recovery_probe_authorized=recovery_probe,
            bootstrap_authorized=bootstrap_authorized,
            enforce=True,
            longitudinal_core=longitudinal,
        )
        if checkpoint.composition.result != "ALLOW":
            raise ValueError("EXECUTION_PERMIT_G13_INVALID")
        if bootstrap_authorized and bootstrap_grant is not None:
            from app.authority.bootstrap import consume_bootstrap_authority
            consume_bootstrap_authority(
                session,
                grant_id=bootstrap_grant.bootstrap_authority_id,
                action_id=acquisition_id,
                action_kind=permit.action_kind,
                amount=Decimal(budget),
                mandate_id=mandate_id,
                run_id=run.run_id,
            )
    except ValueError as error:
        if str(error).startswith("EXECUTION_PERMIT_"):
            raise
        raise ValueError("EXECUTION_PERMIT_G13_INVALID") from error
    except Exception as error:
        raise ValueError("EXECUTION_PERMIT_G13_INVALID") from error


def _gateway_reconciled_without_payment(code: str, call: TelegraphCall | None, gateway_http_status: int | None = None) -> bool:
    """Return true only for an explicit x402 challenge with no settlement.

    A 402 ``PAYMENT_REQUIRED`` response is a gateway challenge.  No payment
    has been attempted yet, so retaining the reservation as payment-uncertain
    deadlocks the autonomous scheduler.  Other payment errors remain
    uncertain because they may occur after a payment attempt.
    """
    return bool(
        code == NO_PAYMENT_GATEWAY_FAILURE
        and gateway_http_status == 402
    )


def execute_one(mandate_id, acquisition_id):
    session = SessionLocal()
    network_attempted = False
    failure_stage = "PRE_NETWORK"
    gateway_http_status: int | None = None
    budget = Decimal("0")
    claimed = False
    try:
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one_or_none()
        task = session.get(AcquisitionTask, acquisition_id)
        if mandate is None or task is None or task.mandate_id != mandate_id:
            return "INVALID_MANDATE"
        if task.status in {"SUCCEEDED", "FAILED", "RUNNING"}:
            return "ALREADY_" + task.status
        if mandate.status in {"TICKETED", "DECIDED", "FAILED"}:
            return "MANDATE_TERMINAL"
        tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).order_by(AcquisitionTask.ordinal, AcquisitionTask.acquisition_id).all()
        pending = [t for t in tasks if t.status in {"QUEUED", "PENDING"}]
        if any(t.status == "RUNNING" for t in tasks) or not pending or pending[0].acquisition_id != acquisition_id:
            return "WAITING_FOR_PREVIOUS_ACQUISITION"
        if mandate.status == "RECEIVED": transition_mandate(session, mandate, MandateStatus.PLANNED)
        if mandate.status == "PLANNED": transition_mandate(session, mandate, MandateStatus.ACQUIRING)
        task.status = "RUNNING"
        task.attempt_count += 1
        task.started_at = now()
        claimed = True
        session.commit()
        cap = maximum(mandate, session)
        if Decimal(mandate.max_budget_usdc) > cap: raise RuntimeError("WORKFLOW_BUDGET_EXCEEDED")
        run = profile = None
        preliminary_g13 = None
        throttle_limit = None
        throttle_ok = False
        recovery_observation_permitted = False
        bootstrap_authorized = False
        bootstrap_grant = None
        if mandate.origin == "AUTONOMOUS":
            from app.authority.delegated import resolve_profile
            from app.authority.runtime import evaluate_current_g13
            run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
            if run is None: raise RuntimeError("AUTONOMY_RUN_MISSING")
            profile = resolve_profile(session, mandate.agent_identity_id)
            per_action_cap = Decimal(profile.per_action_budget) if profile.per_action_budget is not None else cap
            configured_throttle = (profile.human_review_thresholds or {}).get("throttle_max_usdc")
            economic_ceiling = cap if profile.unlimited_budget else Decimal(profile.per_action_budget or profile.economic_budget)
            throttle_limit = Decimal(str(configured_throttle)) if configured_throttle is not None else economic_ceiling / Decimal("2")
            preliminary_g13 = evaluate_current_g13(session, mandate.agent_identity_id)
            recovery_probe_authorized = (
                preliminary_g13.policy_version == G13_REVIEW_RECOVERY_POLICY_VERSION
                and preliminary_g13.result_core.get("recovery_probe_authorized") is True
            )
            from app.authority.recovery import latest_operator_recovery
            from app.authority.runtime import (
                G13_RECOVERY_OBSERVATION_EVENT_TYPE,
                recovery_observation_available,
            )
            recovery_observation_permitted = (
                preliminary_g13.result == "REVIEW"
                and not recovery_probe_authorized
                and preliminary_g13.result_core.get("sole_blocker")
                == "G13_CURRENT_CRITICAL_OBSERVATION_MISSING"
                and recovery_observation_available(session, mandate.agent_identity_id)
            )
            from app.authority.bootstrap import bootstrap_eligibility
            identity = session.get(AgentIdentity, mandate.agent_identity_id)
            bootstrap_authorized, _bootstrap_reason, bootstrap_grant = bootstrap_eligibility(
                session,
                identity=identity,
                policy=session.get(AutonomyPolicy, run.policy_id),
                profile=profile,
                g13_core=preliminary_g13,
                action_kind="TELEGRAPH_HTTP_ACQUISITION",
                amount=Decimal(mandate.max_budget_usdc),
            )
            if (
                preliminary_g13.result == "HALT"
                or (
                    preliminary_g13.result == "REVIEW"
                    and not recovery_probe_authorized
                    and not recovery_observation_permitted
                    and not bootstrap_authorized
                )
            ):
                raise RuntimeError("G13_" + preliminary_g13.result)
            if preliminary_g13.result == "THROTTLE" and preliminary_g13.result_core.get("operator_recovery_canary"):
                recovery = preliminary_g13.input_core.get("operator_recovery") or {}
                throttle_limit = min(
                    economic_ceiling,
                    Decimal(str(recovery.get("canary_budget_usdc", "0"))),
                )
        else:
            per_action_cap = MAX_SINGLE_ACQUISITION_USDC
        reservation = verify_spend_reservation(session, mandate_id, cap, mandate.origin)
        available = reservation.reserved_usdc - uncertain_hold(session, mandate_id)
        budget = min(available, per_action_cap)
        if budget <= 0: raise RuntimeError("BUDGET_EXHAUSTED")
        if mandate.origin == "AUTONOMOUS":
            if preliminary_g13.result == "THROTTLE":
                budget = min(budget, throttle_limit)
                if budget <= 0:
                    raise RuntimeError("G13_THROTTLE_CONSTRAINTS_REQUIRED")
            throttle_ok = budget <= throttle_limit
        user_credit.verify_reserved(session, mandate, budget)
        if not task.query.strip(): raise RuntimeError("ACQUISITION_QUERY_INVALID")
        adapter = configured_acquisition_adapter(
            timeout_seconds=GATEWAY_REQUEST_TIMEOUT_SECONDS,
            urlopen_fn=urlopen,
        )
        call = TelegraphCall(
            mandate_id=mandate_id,
            acquisition_id=acquisition_id,
            causal_request_id=mandate_id,
            raw_response={"access_plane": {"provider": getattr(adapter, "provider", None), "access_mechanism": getattr(adapter, "access_mechanism", None), "payment_rail": getattr(adapter, "payment_rail", None)}},
            resource_provider=getattr(adapter, "provider", None),
            access_mechanism=getattr(adapter, "access_mechanism", None),
            payment_rail=getattr(adapter, "payment_rail", None),
            status="REQUESTED",
            cost_usd=None,
        )
        session.add(call)
        request_metadata = {"budget_usdc": str(budget), "origin": mandate.origin}
        if mandate.origin == "AUTONOMOUS":
            request_metadata.update({
                "g13_policy_evaluation_id": preliminary_g13.policy_evaluation_id,
                "g13_policy_version": preliminary_g13.policy_version,
                "g13_result": preliminary_g13.result,
                "throttle_limit_usdc": str(throttle_limit) if throttle_limit is not None else None,
                "throttled_constraints_satisfied": throttle_ok,
                "recovery_probe_authorized": recovery_probe_authorized,
                "bootstrap_authorized": bootstrap_authorized,
                "authorization_source": "BOOTSTRAP" if bootstrap_authorized else "NORMAL_G13",
            })
        session.add(UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id, event_type="TELEGRAPH_REQUEST", metadata_=request_metadata))
        session.commit()  # Durable RUNNING claim before any outbound request.
        if mandate.origin == "AUTONOMOUS" and recovery_observation_permitted:
            # Consume the single recovery observation for this episode BEFORE
            # opening the external connection. Any later external failure
            # still counts as the fresh observation G13 will re-evaluate, and
            # no second observation is granted for the same recovery episode.
            recovery_event = latest_operator_recovery(session, mandate.agent_identity_id)
            existing_consumption = session.query(UsageEvent).filter(
                UsageEvent.event_type == G13_RECOVERY_OBSERVATION_EVENT_TYPE,
                UsageEvent.metadata_["recovery_event_id"].astext == str(recovery_event.event_id),
            ).one_or_none()
            if existing_consumption is None:
                session.add(UsageEvent(
                    mandate_id=mandate_id,
                    acquisition_id=acquisition_id,
                    event_type=G13_RECOVERY_OBSERVATION_EVENT_TYPE,
                    metadata_={
                        "recovery_event_id": str(recovery_event.event_id),
                        "agent_id": mandate.agent_identity_id,
                        "autonomy_run_id": run.run_id,
                        "sole_blocker": "G13_CURRENT_CRITICAL_OBSERVATION_MISSING",
                        "g13_policy_evaluation_id": preliminary_g13.policy_evaluation_id,
                        "g13_policy_version": preliminary_g13.policy_version,
                    },
                ))
                session.commit()  # Consumption durable before external traffic.
        from app.authority.runtime import observe_authority_shadow
        observe_authority_shadow(
            mandate_id,
            phase="PRE_ACQUISITION",
            acquisition_id=acquisition_id,
            g12_verified=True,
            throttled_constraints_satisfied=throttle_ok,
        )
        permit = None
        if mandate.origin == "AUTONOMOUS":
            from app.authority.delegated import issue_execution_permit, consume_execution_permit
            from app.authority.runtime import run_pre_next_action_authority_check
            checkpoint = run_pre_next_action_authority_check(
                session,
                mandate=mandate,
                acquisition=task,
                run=run,
                g12_authorized=True,
                g12_reservation=reservation,
                current_runtime_action="CONTINUE_TO_GATEWAY",
                throttled_constraints_satisfied=throttle_ok,
                recovery_probe_authorized=(
                    preliminary_g13.policy_version == G13_REVIEW_RECOVERY_POLICY_VERSION
                    and preliminary_g13.result_core.get("recovery_probe_authorized") is True
                ),
                bootstrap_authorized=bootstrap_authorized,
                enforce=True,
                longitudinal_core=preliminary_g13,
            )
            if checkpoint.composition.result != "ALLOW":
                raise RuntimeError(
                    "AUTHORITY_COMPOSITION_RESTRICTED:"
                    + str(checkpoint.composition.result_core.get("authority_reason", "G13_RESTRICTED"))
                )
            action_material = _build_action_material(
                mandate=mandate, task=task, adapter=adapter,
                amount=budget, reservation=reservation,
            )
            permit = issue_execution_permit(
                session,
                mandate=mandate,
                action_id=acquisition_id,
                action_kind="TELEGRAPH_HTTP_ACQUISITION",
                amount=budget,
                g13_result=checkpoint.longitudinal.result,
                action_material=action_material,
                constraints={
                    "throttle_satisfied": throttle_ok,
                    "recovery_probe_authorized": (
                        preliminary_g13.policy_version == G13_REVIEW_RECOVERY_POLICY_VERSION
                        and preliminary_g13.result_core.get("recovery_probe_authorized") is True
                    ),
                    "bootstrap_authorized": bootstrap_authorized,
                    "bootstrap_authority_id": bootstrap_grant.bootstrap_authority_id if bootstrap_grant is not None else None,
                    "authorization_source": "BOOTSTRAP" if bootstrap_authorized else "NORMAL_G13",
                    "recovery_observation_permitted": recovery_observation_permitted,
                    "throttle_limit_usdc": str(throttle_limit) if throttle_limit is not None else None,
                    "g12_reservation_verified": True,
                    "g12_reserved_usdc": str(reservation.reserved_usdc),
                },
            )
            session.commit()
            if (
                preliminary_g13.policy_version == G13_REVIEW_RECOVERY_POLICY_VERSION
                and preliminary_g13.result_core.get("recovery_probe_authorized") is True
            ):
                existing_probe = session.query(UsageEvent).filter_by(
                    mandate_id=mandate_id,
                    acquisition_id=acquisition_id,
                    event_type="G13_RECOVERY_PROBE_STARTED",
                ).one_or_none()
                if existing_probe is None:
                    session.add(UsageEvent(
                        mandate_id=mandate_id,
                        acquisition_id=acquisition_id,
                        event_type="G13_RECOVERY_PROBE_STARTED",
                        metadata_={
                            "autonomy_run_id": run.run_id,
                            "recovery_event_id": preliminary_g13.result_core.get("recovery_event_id"),
                            "g13_policy_evaluation_id": preliminary_g13.policy_evaluation_id,
                            "g13_policy_version": preliminary_g13.policy_version,
                            "max_usdc": str(budget),
                            "concurrency_limit": profile.concurrency_limit,
                        },
                    ))
            # All authority-sensitive validation and one-shot consumption are
            # coordinated in one final DB transaction. Commit before network;
            # no DB transaction is held open across adapter.acquire().
            consume_execution_permit(
                session,
                permit.permit_id,
                expected_action_material=action_material,
                authority_validator=lambda locked_permit: _validate_fresh_autonomous_authority(
                    session,
                    permit=locked_permit,
                    mandate_id=mandate_id,
                    acquisition_id=acquisition_id,
                    run=run,
                    adapter=adapter,
                    action_material=action_material,
                    budget=budget,
                    throttle_ok=throttle_ok,
                ),
            )
            session.commit()
        network_attempted = True
        failure_stage = "NETWORK"
        try:
            result = adapter.acquire(
                query=task.query,
                requested_intent=task.requested_intent,
                causal_request_id=mandate_id,
                budget_usdc=budget,
            )
        except AcquisitionAdapterError as error:
            gateway_http_status = error.http_status
            # A response received over HTTP is durably retained before the
            # existing failure path applies its task/payment transitions.
            # HTTP error bodies intentionally retain the prior behavior: they
            # are classified, while the call remains unreconciled until the
            # normal exception path persists its state.
            if error.http_status is None and error.raw_payload is not None:
                call.raw_response = error.raw_payload
                call.status = "RECEIVED"
                session.commit()
                failure_stage = "POST_RESPONSE"
            raise RuntimeError(error.code) from error
        raw = result.raw_payload
        actual = result.cost_usdc
        call.raw_response = raw
        call.status = "RECEIVED"
        session.commit()  # Preserve Gateway response before Evidence normalization.
        failure_stage = "POST_RESPONSE"
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one()
        queued = session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id==mandate_id,AcquisitionTask.status.in_(["QUEUED","PENDING"])).count()
        finalize = not queued and uncertain_hold(session,mandate_id)==0
        user_credit.settle(session,mandate,acquisition_id,actual,finalize=finalize)
        settle_spend(session, mandate_id, actual, cap, mandate.origin, finalize=finalize)
        for name in ["miner_id", "miner_name", "intent", "signal_hash", "duration_ms", "reasoning"]:
            setattr(call, name, getattr(result, name))
        call.miner_id = str(result.miner_id)
        call.warnings = result.warnings
        call.cost_usd = actual
        task.resource_provider = result.provider
        task.access_mechanism = result.access_mechanism
        task.payment_rail = result.payment_rail
        task.resource_metadata = {
            "provider": result.provider,
            "access_mechanism": result.access_mechanism,
            "payment_rail": result.payment_rail,
        }
        call.resource_provider = result.provider
        call.access_mechanism = result.access_mechanism
        call.payment_rail = result.payment_rail
        call.status = "SUCCEEDED"
        call.completed_at = task.completed_at = now()
        task.status = "SUCCEEDED"
        for kind in ["TELEGRAPH_RESPONSE","ACQUISITION_COMPLETED"]:
            session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type=kind,metadata_={"origin":mandate.origin}))
        session.commit()
        return "ACQUISITION_COMPLETED"
    except Exception as error:
        session.rollback()
        if not claimed: raise
        exception_type = type(error).__name__
        exception_message = str(error)[:500]
        effective_gateway_url = os.environ.get("GATEWAY_URL", "<UNSET>")
        run_id_for_log = getattr(locals().get("run"), "run_id", None)
        logger.error(
            "ACQUISITION_EXCEPTION acquisition_id=%s run_id=%s mandate_id=%s exception_type=%s exception_message=%r network_attempted=%s failure_stage=%s gateway_url=%r",
            acquisition_id,
            run_id_for_log,
            mandate_id,
            exception_type,
            exception_message,
            network_attempted,
            failure_stage,
            effective_gateway_url,
        )
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one()
        task = session.get(AcquisitionTask,acquisition_id)
        message = getattr(error, "detail", str(error))
        code = next((item for item in KNOWN_FAILURE_CODES if message == item or message.startswith(item + ":")), "GATEWAY_UNAVAILABLE")
        if not network_attempted and code == "GATEWAY_UNAVAILABLE":
            code = "WORKER_INTERNAL_PRE_NETWORK"
        task.status = "FAILED"
        task.failure_code = code
        task.started_at = task.started_at or now()
        task.completed_at = now()
        task.attempt_count = max(task.attempt_count,1)
        # A claim failing before its first commit also needs explicit transitions.
        if mandate.status == "RECEIVED": transition_mandate(session,mandate,MandateStatus.PLANNED)
        if mandate.status == "PLANNED": transition_mandate(session,mandate,MandateStatus.ACQUIRING)
        call = session.query(TelegraphCall).filter_by(acquisition_id=acquisition_id).one_or_none()
        episode_id = None
        if is_external_dependency_failure(code):
            existing_episode = next(
                (
                    str((event.metadata_ or {}).get("failure_episode_id"))
                    for event in (
                        session.query(UsageEvent)
                        .filter_by(mandate_id=mandate_id, acquisition_id=acquisition_id)
                        .order_by(UsageEvent.created_at.desc(), UsageEvent.event_id.desc())
                        .all()
                        or []
                    )
                    if event is not None and (event.metadata_ or {}).get("failure_episode_id")
                ),
                None,
            )
            episode_id = existing_episode or failure_episode_id(
                agent_identity_id=getattr(mandate, "agent_identity_id", None),
                mandate_id=mandate_id,
                acquisition_id=acquisition_id,
                causal_request_id=getattr(call, "causal_request_id", None),
            )
        no_payment_reconciled = _gateway_reconciled_without_payment(code, call, gateway_http_status)
        if call:
            call.status = (
                "RECONCILED_NO_PAYMENT"
                if no_payment_reconciled
                else "PAYMENT_UNCERTAIN" if network_attempted else "NOT_EXECUTED"
            )
            if no_payment_reconciled:
                call.raw_response = {
                    **(call.raw_response or {}),
                    "gateway_http_status": gateway_http_status,
                    "payment_state": "RECONCILED_NO_PAYMENT",
                }
                call.cost_usd = Decimal("0.000000")
            call.completed_at = now()
        failure_metadata={
            "failure_code": code,
            "network_attempted": network_attempted,
            "failure_stage": failure_stage,
            "exception_type": exception_type,
            "exception_message": exception_message,
            "gateway_url": effective_gateway_url,
        }
        if episode_id is not None:
            failure_metadata.update({
                "failure_episode_id": episode_id,
                "failure_episode_schema_version": FAILURE_EPISODE_SCHEMA_VERSION,
                "provider": FAILURE_EPISODE_PROVIDER,
                "access_mechanism": FAILURE_EPISODE_ACCESS_MECHANISM,
                "originating_call": call.telegraph_call_id if call is not None else None,
                "autonomy_run_id": run_id_for_log,
                "failure_class": code,
            })
        episode_metadata = (
            {
                "failure_episode_id": episode_id,
                "failure_episode_schema_version": FAILURE_EPISODE_SCHEMA_VERSION,
                "provider": FAILURE_EPISODE_PROVIDER,
                "access_mechanism": FAILURE_EPISODE_ACCESS_MECHANISM,
                "originating_call": call.telegraph_call_id if call is not None else None,
                "autonomy_run_id": run_id_for_log,
                "failure_class": code,
            }
            if episode_id is not None
            else {}
        )
        session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_FAILED",metadata_=failure_metadata))
        if no_payment_reconciled:
            session.add(UsageEvent(
                mandate_id=mandate_id,
                acquisition_id=acquisition_id,
                event_type="ACQUISITION_PAYMENT_RECONCILED",
                metadata_={
                    "settled": False,
                    "payment_state": "RECONCILED_NO_PAYMENT",
                    "settled_usdc": "0.000000",
                    "actual_cost_usdc": "0.000000",
                    "failure_code": code,
                    "gateway_http_status": 402,
                    **episode_metadata,
                },
            ))
        elif network_attempted:
            session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_PAYMENT_UNCERTAIN",metadata_={"held_budget_usdc":str(budget),"failure_code":code, **episode_metadata}))
        session.commit()
        return code
    finally:
        session.close()


def advance(mandate_id):
    """Resume dispatch on redelivery without repeating completed payment."""
    session = SessionLocal()
    try:
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one_or_none()
        if mandate is None: return "INVALID_MANDATE"
        if mandate.status in {"TICKETED","FAILED"}: return mandate.status
        tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).order_by(AcquisitionTask.ordinal).all()
        if any(t.status=="RUNNING" for t in tasks): return "WAITING_FOR_ACQUISITIONS"
        queued = next((t for t in tasks if t.status in {"QUEUED","PENDING"}),None)
        if queued:
            next_id = queued.acquisition_id
            session.commit()
            from app.workers.tasks import execute_acquisition
            execute_acquisition.delay(mandate_id,next_id)
            return "ACQUISITION_CONTINUED"
        blocked = next((t for t in tasks if t.status == "FAILED" and t.failure_code in {"G13_REVIEW", "G13_HALT"}), None)
        if blocked is not None:
            reservation = session.get(PublicManualSpendReservation, mandate_id)
            if reservation and reservation.status == "RESERVED" and uncertain_hold(session, mandate_id) == 0:
                user_credit.release(session, mandate)
                release_spend_reservation(session, mandate_id, mandate.origin)
            if mandate.status != MandateStatus.FAILED.value:
                transition_mandate(session, mandate, MandateStatus.FAILED, blocked.failure_code)
            finalize_http_run(session, mandate_id, failure_code=blocked.failure_code)
            session.commit()
            return blocked.failure_code
        if mandate.status == "ACQUIRING":
            reservation = session.get(PublicManualSpendReservation,mandate_id)
            if reservation and reservation.status=="RESERVED" and uncertain_hold(session,mandate_id)==0:
                user_credit.release(session,mandate)
                if reservation.reserved_usdc>0:
                    settle_spend(session,mandate_id,Decimal("0"),maximum(mandate),mandate.origin,finalize=True)
                else:
                    release_spend_reservation(session,mandate_id,mandate.origin)
            transition_mandate(session,mandate,MandateStatus.EVALUATING)
        session.commit()
    finally: session.close()
    from app.workers.tasks import evaluate_mandate
    return evaluate_mandate(mandate_id)
