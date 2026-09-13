"""Persistent, fail-closed autonomy scheduling.

REPLAY_ONLY is always DB-only.  TELEGRAPH_HTTP is executable only when both
the global switch and the explicitly enabled policy permit the bounded rail.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.domain.mandates import (
    AcquisitionStatus,
    AcquisitionTask,
    AutonomyPolicy,
    AutonomyRun,
    ERC8183Job,
    Mandate,
    MandateStatus,
    MandateTransition,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.agents.identity import get_policy_identity, mandate_attribution, policy_identity_required
from app.erc8183.evidence import replay_persisted
from app.public_safety import m2m_max_workflow_usdc, reserve_autonomous_spend
from app.domain.mandates import AgentAuthorityProfile
from app.authority.delegated import full_autonomy_enabled, resolve_profile

PAID_MIN_CADENCE_SECONDS = 900
MODES = {"TELEGRAPH_HTTP", "TELEGRAPH_ERC8183", "REPLAY_ONLY"}
ACTIVE_RUN_STATES = {"SCHEDULED", "CLAIMED", "RUNNING", "WAITING_EXTERNAL"}
FORBIDDEN_TEMPLATE_KEYS = {"private_key", "secret", "credential", "calldata", "spender", "callback"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def global_enabled() -> bool:
    return os.environ.get("AUTONOMY_GLOBAL_ENABLED", "false").lower() == "true"


def validate_policy(values: dict) -> None:
    mode = values.get("acquisition_mode")
    if mode not in MODES:
        raise ValueError("AUTONOMY_MODE_INVALID")
    cadence = int(values.get("cadence_seconds", PAID_MIN_CADENCE_SECONDS))
    if cadence < 1:
        raise ValueError("AUTONOMY_CADENCE_INVALID")
    if int(values.get("dedupe_window_seconds", cadence)) < cadence:
        raise ValueError("AUTONOMY_DEDUPE_WINDOW_INVALID")
    if int(values.get("max_runs_per_day", 0)) < 1 or int(values.get("max_concurrent_runs", 0)) < 1:
        raise ValueError("AUTONOMY_LIMIT_INVALID")
    for field in ("max_usdc_per_run", "max_usdc_per_day"):
        if Decimal(str(values.get(field, "0"))) < 0:
            raise ValueError("AUTONOMY_BUDGET_INVALID")
    if mode == "TELEGRAPH_HTTP" and not values.get("allow_telegraph_http", False):
        raise ValueError("AUTONOMY_HTTP_NOT_ALLOWED")
    if mode == "TELEGRAPH_ERC8183" and not values.get("allow_erc8183", False):
        raise ValueError("AUTONOMY_ERC8183_NOT_ALLOWED")
    if values.get("state", "DRAFT") not in {"DRAFT", "ACTIVE", "PAUSED", "DISABLED"}:
        raise ValueError("AUTONOMY_STATE_INVALID")
    _validate_template(values.get("mandate_template", {}))


def _validate_template(value: object) -> None:
    """Policies describe a mandate, never a signing or gateway capability."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(forbidden in normalized for forbidden in FORBIDDEN_TEMPLATE_KEYS):
                raise ValueError("AUTONOMY_TEMPLATE_FORBIDDEN_FIELD")
            _validate_template(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_template(nested)


def execution_slot(policy: AutonomyPolicy, when: datetime, cadence: int | None = None) -> datetime:
    instant = when.astimezone(timezone.utc)
    seconds = int(instant.timestamp())
    cadence = cadence or policy.cadence_seconds
    return datetime.fromtimestamp(seconds - seconds % cadence, tz=timezone.utc)


def _authority_profile(session, policy: AutonomyPolicy) -> AgentAuthorityProfile | None:
    identity = get_policy_identity(session, policy)
    if identity is None:
        return None
    try:
        return resolve_profile(session, identity.agent_id)
    except ValueError:
        return None


def _effective_cadence(policy: AutonomyPolicy, profile: AgentAuthorityProfile | None) -> int:
    if profile and profile.unlimited_execution_rate:
        # No profile-level rate cap: the autonomy policy remains authoritative.
        return policy.cadence_seconds
    if profile and profile.cadence_policy:
        value = profile.cadence_policy.get("cadence_seconds")
        if value is not None and int(value) >= 1:
            return int(value)
    return policy.cadence_seconds


def idempotency_key(policy: AutonomyPolicy, slot: datetime) -> str:
    material = f"{policy.policy_id}:{policy.version}:{slot.astimezone(timezone.utc).isoformat()}".encode()
    return hashlib.sha256(material).hexdigest()


def _event(session, run: AutonomyRun, event_type: str) -> None:
    existing = next((item for item in session.query(UsageEvent).filter_by(event_type=event_type) if item.metadata_.get("autonomy_run_id") == run.run_id), None)
    if existing is None:
        metadata = {
            "append_only": True,
            "origin": "AUTONOMOUS",
            "agent_id": run.agent_identity_id or "",
            "agent_identity_id": run.agent_identity_id or "",
            "client_id": "prama-internal",
            "autonomy_run_id": run.run_id,
            "policy_id": run.policy_id,
        }
        session.add(UsageEvent(mandate_id=run.mandate_id, event_type=event_type, metadata_=metadata))


def _day_bounds(instant: datetime) -> tuple[datetime, datetime]:
    start = instant.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _planned_cost(policy: AutonomyPolicy, profile: AgentAuthorityProfile | None = None) -> Decimal:
    if policy.acquisition_mode == "REPLAY_ONLY":
        return Decimal("0.000000")
    return Decimal(policy.max_usdc_per_run)


def _budget_reason(session, policy: AutonomyPolicy, instant: datetime, planned: Decimal) -> str | None:
    profile = _authority_profile(session, policy)
    start, end = _day_bounds(instant)
    day_runs = session.query(AutonomyRun).filter(AutonomyRun.policy_id == policy.policy_id, AutonomyRun.scheduled_for >= start, AutonomyRun.scheduled_for < end).all()
    max_runs = policy.max_runs_per_day
    if profile and profile.rolling_budget and profile.rolling_budget.get("max_runs_per_day") is not None:
        max_runs = int(profile.rolling_budget["max_runs_per_day"])
    if max_runs > 0 and len(day_runs) >= max_runs:
        return "DAILY_RUN_CAP"
    active = [run for run in day_runs if run.state in ACTIVE_RUN_STATES]
    concurrency = profile.concurrency_limit if profile and profile.concurrency_limit is not None else policy.max_concurrent_runs
    if concurrency and len(active) >= concurrency:
        return "CONCURRENCY_CAP"
    spent = sum((Decimal(run.actual_cost_usdc) for run in day_runs if run.state == "COMPLETED"), Decimal("0"))
    reserved = sum((Decimal(run.planned_cost_usdc) for run in active), Decimal("0"))
    per_run = (
        profile.per_action_budget
        if profile and not profile.unlimited_budget and profile.per_action_budget is not None
        else policy.max_usdc_per_run
    )
    if planned > Decimal(per_run):
        return "RUN_BUDGET_CAP"
    daily = None
    if profile and not profile.unlimited_budget and profile.rolling_budget:
        daily = profile.rolling_budget.get("max_usdc_per_day")
    daily = Decimal(str(daily)) if daily is not None else Decimal(policy.max_usdc_per_day)
    if spent + reserved + planned > daily:
        return "DAILY_BUDGET_CAP"
    return None


def schedule_due(session, policy: AutonomyPolicy, instant: datetime | None = None, *, global_switch: bool | None = None) -> AutonomyRun | None:
    instant = instant or now()
    enabled = global_enabled() if global_switch is None else global_switch
    if not enabled or not policy.enabled or policy.state != "ACTIVE":
        return None
    profile = _authority_profile(session, policy)
    identity = get_policy_identity(session, policy)
    recovery_probe_authorized = False
    longitudinal = None
    recovery_observation_permitted = False
    if identity is not None:
        from app.authority.runtime import (
            evaluate_current_g13,
            recovery_observation_available,
        )
        longitudinal = evaluate_current_g13(session, identity.agent_id)
        recovery_probe_authorized = (
            longitudinal.policy_version == "g13-d-structural-autonomy-v0.4"
            and longitudinal.result_core.get("recovery_probe_authorized") is True
        )
        # Observation-starvation bypass: exactly one recovery observation is
        # granted per operator_recovery episode when the ONLY active blocker
        # is a missing current critical observation. G13 keeps its REVIEW
        # verdict and will re-evaluate the fresh observation next cycle.
        recovery_observation_permitted = (
            longitudinal.result == "REVIEW"
            and not recovery_probe_authorized
            and longitudinal.result_core.get("sole_blocker")
            == "G13_CURRENT_CRITICAL_OBSERVATION_MISSING"
            and recovery_observation_available(session, identity.agent_id)
        )
        if recovery_observation_permitted and identity.autonomy_state == "REVIEW_REQUIRED":
            # The persisted identity state would short-circuit this schedule
            # below; align the durable state with the current evaluation so
            # the single permitted observation can be created.
            identity.autonomy_state = "ACTIVE"
    if identity is not None and identity.autonomy_state == "HALTED":
        return None
    if identity is not None and identity.autonomy_state == "REVIEW_REQUIRED" and not recovery_probe_authorized:
        return None
    if identity is not None and full_autonomy_enabled(identity.agent_id) and profile is None:
        return None
    if profile and not full_autonomy_enabled(identity.agent_id if identity else None):
        return None
    if longitudinal is not None:
        if longitudinal.result == "HALT":
            return None
        if (
            longitudinal.result == "REVIEW"
            and not recovery_probe_authorized
            and not recovery_observation_permitted
        ):
            return None
    slot = execution_slot(policy, instant, _effective_cadence(policy, profile))
    key = idempotency_key(policy, slot)
    existing = session.query(AutonomyRun).filter_by(idempotency_key=key).one_or_none()
    if existing:
        return existing
    if policy.next_run_at and instant < policy.next_run_at:
        return None
    planned = _planned_cost(policy, profile)
    reason = _budget_reason(session, policy, instant, planned)
    run = AutonomyRun(policy_id=policy.policy_id, agent_identity_id=identity.agent_id if identity else None, scheduled_for=slot, idempotency_key=key, state="SKIPPED" if reason else "SCHEDULED", planned_cost_usdc=planned, actual_cost_usdc=Decimal("0.000000"), skip_reason=reason)
    try:
        session.add(run); session.flush()
    except IntegrityError:
        session.rollback()
        return session.query(AutonomyRun).filter_by(idempotency_key=key).one()
    policy.last_run_at = instant
    policy.next_run_at = slot + timedelta(seconds=_effective_cadence(policy, profile))
    _event(session, run, "AUTONOMY_RUN_SKIPPED" if reason else "AUTONOMY_RUN_SCHEDULED")
    return run


def claim_run(session, run_id: str) -> AutonomyRun | None:
    run = session.query(AutonomyRun).filter_by(run_id=run_id, state="SCHEDULED").with_for_update(skip_locked=True).one_or_none()
    if run is None:
        return None
    run.state = "CLAIMED"; run.started_at = now(); _event(session, run, "AUTONOMY_RUN_STARTED")
    return run


def execute_claimed(session, run: AutonomyRun) -> str:
    policy = session.get(AutonomyPolicy, run.policy_id)
    if policy is None:
        run.state = "FAILED"; run.failure_code = "POLICY_MISSING"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    if policy.acquisition_mode == "TELEGRAPH_HTTP":
        if not global_enabled() or not policy.enabled or policy.state != "ACTIVE":
            run.state = "FAILED"; run.failure_code = "AUTONOMY_DISABLED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        if not policy.allow_telegraph_http or policy.read_only_replay:
            run.state = "FAILED"; run.failure_code = "HTTP_RAIL_NOT_ALLOWED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        if run.mandate_id:
            return "ALREADY_EXECUTED"
        instruction = policy.mandate_template.get("instruction")
        title = policy.mandate_template.get("title", "Autonomous PRAMA mandate")
        if not isinstance(instruction, str) or not instruction.strip() or not isinstance(title, str):
            run.state = "FAILED"; run.failure_code = "MANDATE_TEMPLATE_INVALID"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        try:
            identity = policy_identity_required(session, policy)
        except ValueError as error:
            run.state = "FAILED"; run.failure_code = str(error)[:100]; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
            return run.state
        if not full_autonomy_enabled(identity.agent_id):
            run.state = "FAILED"; run.failure_code = "FULL_AUTONOMY_DISABLED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
            return run.state
        try:
            authority_profile = resolve_profile(session, identity.agent_id)
        except ValueError as error:
            run.state = "FAILED"; run.failure_code = str(error)[:100]; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
            return run.state
        if (not authority_profile.unlimited_budget and authority_profile.economic_budget is None) or not authority_profile.external_execution_allowed or not authority_profile.telegraph_allowed:
            run.state = "FAILED"; run.failure_code = "AUTHORITY_ACTION_NOT_ALLOWED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
            return run.state
        run.agent_identity_id = identity.agent_id
        mandate = Mandate(
            actor_id=identity.agent_id, agent_id=identity.agent_id, agent_identity_id=identity.agent_id, client_id="prama-internal",
            text=instruction.strip(), mandate_type="AUTONOMOUS",
            constraints={"title": title, "autonomy_policy_id": policy.policy_id, "autonomy_run_id": run.run_id, "authority_profile_id": authority_profile.authority_profile_id},
            max_budget_usdc=Decimal(run.planned_cost_usdc), status=MandateStatus.RECEIVED.value,
            origin="AUTONOMOUS", autonomy_policy_id=policy.policy_id, autonomy_run_id=run.run_id,
        )
        session.add(mandate); session.flush()
        # A profile with no independent cap still inherits the effective G12
        # workflow ceiling; every paid run therefore has a numeric reservation.
        try:
            g12_maximum = (
                m2m_max_workflow_usdc()
                if authority_profile.unlimited_budget
                else Decimal(authority_profile.economic_budget)
            )
            reserve_autonomous_spend(
                session,
                mandate.mandate_id,
                Decimal(run.planned_cost_usdc),
                maximum=g12_maximum,
            )
        except Exception as error:
            code = getattr(error, "detail", str(error))
            mandate.status = MandateStatus.FAILED.value
            session.add(MandateTransition(mandate_id=mandate.mandate_id, from_status=MandateStatus.RECEIVED.value, to_status=MandateStatus.FAILED.value, reason=str(code)[:255]))
            run.state = "FAILED"; run.failure_code = str(code)[:100]; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
            return run.state
        acquisitions = policy.mandate_template.get("acquisitions")
        if not isinstance(acquisitions, list) or not acquisitions:
            acquisitions = [{"query": mandate.text, "requested_intent": None}]
        tasks = []
        for ordinal, item in enumerate(acquisitions):
            if not isinstance(item, dict) or not isinstance(item.get("query", mandate.text), str) or not item.get("query", mandate.text).strip():
                run.state = "FAILED"; run.failure_code = "MANDATE_TEMPLATE_INVALID"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
            task = AcquisitionTask(
                mandate_id=mandate.mandate_id, query=item.get("query", mandate.text).strip(),
                requested_intent=item.get("requested_intent") if isinstance(item.get("requested_intent"), str) else None,
                required=bool(item.get("required", True)), status=AcquisitionStatus.QUEUED.value, ordinal=ordinal,
            )
            tasks.append(task)
        session.add_all(tasks); session.flush()
        metadata = mandate_attribution(mandate)
        metadata.update({"autonomy_run_id": run.run_id, "autonomy_policy_id": policy.policy_id})
        queued_metadata = {**metadata}
        session.add_all([
            MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="autonomy scheduler due slot"),
            UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_=metadata),
            *[UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_=queued_metadata) for task in tasks],
        ])
        run.mandate_id = mandate.mandate_id; run.state = "RUNNING"; run.skip_reason = None
        return "ACQUISITION_QUEUED"
    if policy.acquisition_mode != "REPLAY_ONLY" or not policy.read_only_replay:
        run.state = "WAITING_EXTERNAL"; run.skip_reason = "PAID_RAIL_DISABLED"; return run.state
    source_id = policy.mandate_template.get("erc8183_job_id")
    if not isinstance(source_id, str):
        run.state = "FAILED"; run.failure_code = "REPLAY_SOURCE_MISSING"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    try:
        replay = replay_persisted(session, source_id)
    except Exception:
        run.state = "FAILED"; run.failure_code = "REPLAY_FAILED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    if not replay["matches"]:
        run.state = "FAILED"; run.failure_code = "REPLAY_MISMATCH"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    source = session.get(ERC8183Job, source_id)
    run.state = "COMPLETED"; run.mandate_id = source.mandate_id; run.erc8183_job_id = source_id; run.ticket_id = source.ticket_id; run.actual_cost_usdc = Decimal("0.000000"); run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_COMPLETED")
    return run.state


def _actual_cost(session, mandate_id: str) -> Decimal:
    return sum((Decimal(call.cost_usd or 0) for call in session.query(TelegraphCall).filter_by(mandate_id=mandate_id, status="SUCCEEDED")), Decimal("0.000000"))


def finalize_http_run(session, mandate_id: str, *, failure_code: str | None = None) -> str | None:
    """Close the exact run that originated this autonomous mandate.

    This function is called only after the existing pipeline reaches a durable
    terminal state; it never sends a request, payment, or chain transaction.
    """
    run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
    if run is None or run.state in {"COMPLETED", "FAILED", "SKIPPED"}:
        return run.state if run else None
    actual = _actual_cost(session, mandate_id)
    run.actual_cost_usdc = actual
    run.finished_at = now()
    if failure_code:
        run.state = "FAILED"; run.failure_code = failure_code[:100]; _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    mandate = session.get(Mandate, mandate_id)
    ticket = session.query(Ticket).filter_by(mandate_id=mandate_id).one_or_none()
    if mandate is None or mandate.status != MandateStatus.TICKETED.value or ticket is None:
        run.state = "FAILED"; run.failure_code = "AUTONOMY_PIPELINE_INCOMPLETE"; _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    run.ticket_id = ticket.ticket_id; run.state = "COMPLETED"; run.failure_code = None; _event(session, run, "AUTONOMY_RUN_COMPLETED")
    return run.state


def recover_runs(session) -> list[str]:
    recovered = []
    for run in session.query(AutonomyRun).filter(AutonomyRun.state.in_(["CLAIMED", "RUNNING"])).all():
        run.state = "SCHEDULED"; run.started_at = None; recovered.append(run.run_id)
    return recovered


def status(session, instant: datetime | None = None) -> dict:
    instant = instant or now(); start, end = _day_bounds(instant)
    policies = session.query(AutonomyPolicy).all()
    runs = session.query(AutonomyRun).all()
    today = [run for run in runs if start <= run.scheduled_for < end]
    active = [run for run in runs if run.state in ACTIVE_RUN_STATES]
    next_due = min((policy.next_run_at for policy in policies if policy.enabled and policy.next_run_at), default=None)
    return {"global_enabled": global_enabled(), "active_policy_count": sum(1 for policy in policies if policy.enabled and policy.state == "ACTIVE"), "active_run_count": len(active), "today_run_count": len(today), "today_spend_usdc": str(sum((Decimal(run.actual_cost_usdc) for run in today), Decimal("0"))), "next_due_at": next_due, "autonomous_runs_total": len(runs), "completed": sum(1 for run in runs if run.state == "COMPLETED"), "skipped": sum(1 for run in runs if run.state == "SKIPPED"), "failed": sum(1 for run in runs if run.state == "FAILED"), "actual_usdc_spend": str(sum((Decimal(run.actual_cost_usdc) for run in runs), Decimal("0")))}
