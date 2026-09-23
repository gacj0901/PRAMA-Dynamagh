"""Append-only, canonically hashed operator recovery transitions for G13."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import uuid
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from app.domain.mandates import PublicManualSpendReservation, UsageEvent
from app.epistemic.contracts import canonical_hash


G13_RECOVERY_EVENT_TYPE = "G13_RECOVERY_EVENT"
G13_RECOVERY_EVENT_SCHEMA_VERSION = "g13-operator-reviewed-recovery-event-v0.1"
G13_OPERATOR_RECOVERY_REASON = "TELEGRAPH_ENDPOINT_CORRECTION"
G13_OPERATOR_RECOVERY_POLICY_VERSION = "g13-d-structural-autonomy-v0.3"
G13_OPERATOR_RECOVERY_POLICY_ID = "G13_STRUCTURAL_AUTONOMY_POLICY_V0_3"
G13_OPERATOR_RECOVERY_PREVIOUS_POLICY_VERSION = "g13-d-structural-autonomy-v0.2"
G13_OPERATOR_RECOVERY_ENDPOINT = "http://13.237.89.59:7044"
G13_REVIEW_RECOVERY_SCHEMA_VERSION = "g13-review-recovery-event-v0.1"
G13_REVIEW_RECOVERY_REASON = "RECONCILED_EXTERNAL_FAILURES"
G13_REVIEW_RECOVERY_POLICY_VERSION = "g13-d-structural-autonomy-v0.4"
G13_REVIEW_RECOVERY_POLICY_ID = "G13_STRUCTURAL_AUTONOMY_POLICY_V0_4"
G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION = G13_OPERATOR_RECOVERY_POLICY_VERSION
# Explicit versioned transition v0.4 -> v0.5 for a follow-up reviewed recovery
# after G13_EXTERNAL_ACQUISITION_RECURRENCE.  Distinct schema and constants so
# the historical v0.3->v0.4 contract remains byte-identical and replayable.
G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION = "g13-review-recovery-event-v0.2"
G13_REVIEW_RECOVERY_V2_REASON = "RECONCILED_EXTERNAL_FAILURES"
G13_REVIEW_RECOVERY_V2_POLICY_VERSION = "g13-d-structural-autonomy-v0.5"
G13_REVIEW_RECOVERY_V2_POLICY_ID = "G13_STRUCTURAL_AUTONOMY_POLICY_V0_5"
G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION = G13_REVIEW_RECOVERY_POLICY_VERSION
# Blocker admitted for the v0.4 -> v0.5 recovery.  The historical v0.3 -> v0.4
# recovery only had to satisfy REVIEW shape; for the v2 transition we bind the
# admitted blocker explicitly so only the external-recurrence case clears.
G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER = "G13_EXTERNAL_ACQUISITION_RECURRENCE"
# Same-policy recovery contract: operational recovery under v0.4 does not
# create or select a new normative G13 policy version.
G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION = "g13-review-recovery-current-v0.1"
G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION = "g13-review-recovery-contract-v0.1"
G13_REVIEW_RECOVERY_CURRENT_REASON = "RECONCILED_EXTERNAL_FAILURES"
G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION = G13_REVIEW_RECOVERY_POLICY_VERSION
G13_OPERATOR_RECOVERY_FAILURE_RULES = (
    "G13_REPEATED_EXECUTION_FAILURE",
    "G13_REPEATED_LOCAL_BLOCK",
)

_CANONICAL_FIELDS = (
    "schema_version",
    "agent_identity_id",
    "operator_reviewed",
    "recovery_reason",
    "previous_failure_rules",
    "previous_endpoint_reference",
    "new_endpoint",
    "gateway_deployment_id",
    "authority_mode",
    "previous_policy_version",
    "policy_version",
    "source_event_ids",
    "canary_budget_usdc",
    "canary_execution_limit",
    "created_at",
)

_REVIEW_CANONICAL_FIELDS = (
    "schema_version",
    "agent_identity_id",
    "operator_reviewed",
    "recovery_reason",
    "previous_policy_version",
    "policy_version",
    "source_policy_evaluation_id",
    "source_event_ids",
    "canary_budget_usdc",
    "canary_execution_limit",
    "concurrency_limit",
    "created_at",
)


def _activate_policy_binding_for_recovery(session: Session, event: UsageEvent) -> None:
    """Bind a real SQLAlchemy transition in the same transaction as the event.

    Small in-memory test doubles intentionally do not expose ``bind`` and are
    left as pure event-contract tests; production sessions always do.
    """

    if not hasattr(session, "bind"):
        return
    from app.authority.binding import activate_g13_policy_binding
    from app.authority.binding import current_g13_policy_binding

    payload = event.metadata_ or {}
    # A same-policy recovery is an operational event, not a policy transition.
    # Keep the durable binding (and its identity/hash) unchanged while the
    # recovery remains attributable through its own event payload.
    current = current_g13_policy_binding(session, str(payload["agent_identity_id"]))
    if current is not None and current.effective_policy_version == str(payload["policy_version"]):
        return
    activate_g13_policy_binding(
        session,
        agent_id=str(payload["agent_identity_id"]),
        effective_policy_version=str(payload["policy_version"]),
        previous_policy_version=payload.get("previous_policy_version"),
        source_transition_type=event.event_type,
        source_transition_id=event.event_id,
        recovery_event_id=event.event_id,
        activated_at=event.created_at,
    )

_REVIEW_V2_CANONICAL_FIELDS = (
    *_REVIEW_CANONICAL_FIELDS[:8],
    "source_failure_episode_ids",
    *_REVIEW_CANONICAL_FIELDS[8:],
)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("G13_RECOVERY_CREATED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_recovery_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {field: payload.get(field) for field in _CANONICAL_FIELDS}


def _validate_endpoint_recovery_payload(payload: Mapping[str, Any]) -> bool:
    try:
        material = canonical_recovery_material(payload)
        return (
            material["schema_version"] == G13_RECOVERY_EVENT_SCHEMA_VERSION
            and material["operator_reviewed"] is True
            and material["recovery_reason"] == G13_OPERATOR_RECOVERY_REASON
            and material["authority_mode"] == "BINDING"
            and material["previous_policy_version"] == G13_OPERATOR_RECOVERY_PREVIOUS_POLICY_VERSION
            and material["policy_version"] == G13_OPERATOR_RECOVERY_POLICY_VERSION
            and material["new_endpoint"] == G13_OPERATOR_RECOVERY_ENDPOINT
            and isinstance(material["agent_identity_id"], str)
            and bool(material["agent_identity_id"])
            and isinstance(material["previous_endpoint_reference"], str)
            and bool(material["previous_endpoint_reference"])
            and isinstance(material["gateway_deployment_id"], str)
            and bool(material["gateway_deployment_id"])
            and isinstance(material["previous_failure_rules"], list)
            and material["previous_failure_rules"] == list(G13_OPERATOR_RECOVERY_FAILURE_RULES)
            and isinstance(material["source_event_ids"], list)
            and bool(material["source_event_ids"])
            and material["source_event_ids"] == sorted(set(material["source_event_ids"]))
            and Decimal(str(material["canary_budget_usdc"])) == Decimal("0.010000")
            and material["canary_execution_limit"] == 1
            and payload.get("canonical_hash") == canonical_hash(material)
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def canonical_review_recovery_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {field: payload.get(field) for field in _REVIEW_CANONICAL_FIELDS}


def canonical_review_recovery_v2_material(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {field: payload.get(field) for field in _REVIEW_V2_CANONICAL_FIELDS}


def _validate_review_recovery_payload(payload: Mapping[str, Any]) -> bool:
    try:
        material = canonical_review_recovery_material(payload)
        return (
            material["schema_version"] == G13_REVIEW_RECOVERY_SCHEMA_VERSION
            and material["operator_reviewed"] is True
            and material["recovery_reason"] == G13_REVIEW_RECOVERY_REASON
            and material["previous_policy_version"] == G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION
            and material["policy_version"] == G13_REVIEW_RECOVERY_POLICY_VERSION
            and isinstance(material["agent_identity_id"], str)
            and bool(material["agent_identity_id"])
            and isinstance(material["source_policy_evaluation_id"], str)
            and bool(material["source_policy_evaluation_id"])
            and isinstance(material["source_event_ids"], list)
            and bool(material["source_event_ids"])
            and material["source_event_ids"] == sorted(set(material["source_event_ids"]))
            and Decimal(str(material["canary_budget_usdc"])) == Decimal("0.010000")
            and material["canary_execution_limit"] == 1
            and material["concurrency_limit"] == 1
            and payload.get("canonical_hash") == canonical_hash(material)
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def _validate_review_recovery_v2_payload(payload: Mapping[str, Any]) -> bool:
    try:
        material = canonical_review_recovery_v2_material(payload)
        return (
            material["schema_version"] == G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION
            and material["operator_reviewed"] is True
            and material["recovery_reason"] == G13_REVIEW_RECOVERY_V2_REASON
            and material["previous_policy_version"] == G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION
            and material["policy_version"] == G13_REVIEW_RECOVERY_V2_POLICY_VERSION
            and isinstance(material["agent_identity_id"], str)
            and bool(material["agent_identity_id"])
            and isinstance(material["source_policy_evaluation_id"], str)
            and bool(material["source_policy_evaluation_id"])
            and isinstance(material["source_event_ids"], list)
            and bool(material["source_event_ids"])
            and material["source_event_ids"] == sorted(set(material["source_event_ids"]))
            and isinstance(material["source_failure_episode_ids"], list)
            and bool(material["source_failure_episode_ids"])
            and material["source_failure_episode_ids"]
            == sorted(set(material["source_failure_episode_ids"]))
            and Decimal(str(material["canary_budget_usdc"])) == Decimal("0.010000")
            and material["canary_execution_limit"] == 1
            and material["concurrency_limit"] == 1
            and payload.get("canonical_hash") == canonical_hash(material)
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def _validate_current_review_recovery_payload(payload: Mapping[str, Any]) -> bool:
    try:
        material = {
            "schema_version": payload.get("schema_version"),
            "recovery_contract_version": payload.get("recovery_contract_version"),
            "agent_identity_id": payload.get("agent_identity_id"),
            "operator_reviewed": payload.get("operator_reviewed"),
            "recovery_reason": payload.get("recovery_reason"),
            "policy_version": payload.get("policy_version"),
            "source_policy_evaluation_id": payload.get("source_policy_evaluation_id"),
            "source_policy_binding_id": payload.get("source_policy_binding_id"),
            "source_policy_binding_hash": payload.get("source_policy_binding_hash"),
            "source_event_ids": payload.get("source_event_ids"),
            "source_failure_episode_ids": payload.get("source_failure_episode_ids"),
            "canary_budget_usdc": payload.get("canary_budget_usdc"),
            "canary_execution_limit": payload.get("canary_execution_limit"),
            "concurrency_limit": payload.get("concurrency_limit"),
            "created_at": payload.get("created_at"),
        }
        return (
            material["schema_version"] == G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION
            and material["recovery_contract_version"] == G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION
            and material["agent_identity_id"]
            and material["operator_reviewed"] is True
            and material["recovery_reason"] == G13_REVIEW_RECOVERY_CURRENT_REASON
            and material["policy_version"] == G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION
            and material["source_policy_evaluation_id"]
            and material["source_policy_binding_id"]
            and material["source_policy_binding_hash"]
            and isinstance(material["source_event_ids"], list)
            and material["source_event_ids"] == sorted(set(material["source_event_ids"]))
            and material["source_event_ids"]
            and isinstance(material["source_failure_episode_ids"], list)
            and material["source_failure_episode_ids"] == sorted(set(material["source_failure_episode_ids"]))
            and material["source_failure_episode_ids"]
            and Decimal(str(material["canary_budget_usdc"])) == Decimal("0.010000")
            and material["canary_execution_limit"] == 1
            and material["concurrency_limit"] == 1
            and payload.get("canonical_hash") == canonical_hash(material)
        )
    except (InvalidOperation, KeyError, TypeError, ValueError):
        return False


def validate_recovery_payload(payload: Mapping[str, Any]) -> bool:
    return (
        _validate_endpoint_recovery_payload(payload)
        or _validate_review_recovery_payload(payload)
        or _validate_review_recovery_v2_payload(payload)
        or _validate_current_review_recovery_payload(payload)
    )


def recovery_event_id(payload: Mapping[str, Any]) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"prama-dynamagh:g13-recovery:{payload['canonical_hash']}"))


def record_operator_recovery(
    session: Session,
    *,
    agent_identity_id: str,
    previous_failure_rules: Iterable[str],
    previous_endpoint_reference: str,
    new_endpoint: str,
    gateway_deployment_id: str,
    authority_mode: str,
    previous_policy_version: str,
    source_event_ids: Iterable[str],
    created_at: datetime | None = None,
    canary_budget_usdc: Decimal = Decimal("0.010000"),
) -> UsageEvent:
    """Record one idempotent recovery review without mutating prior evidence."""

    instant = created_at or datetime.now(timezone.utc)
    source_ids = sorted(set(str(value) for value in source_event_ids))
    if not source_ids:
        raise ValueError("G13_RECOVERY_SOURCE_EVENTS_REQUIRED")
    existing_sources = {
        value.event_id
        for value in session.query(UsageEvent).filter(UsageEvent.event_id.in_(source_ids)).all()
    }
    if existing_sources != set(source_ids):
        raise ValueError("G13_RECOVERY_SOURCE_EVENT_MISSING")
    material = {
        "schema_version": G13_RECOVERY_EVENT_SCHEMA_VERSION,
        "agent_identity_id": agent_identity_id,
        "operator_reviewed": True,
        "recovery_reason": G13_OPERATOR_RECOVERY_REASON,
        "previous_failure_rules": sorted(set(str(value) for value in previous_failure_rules)),
        "previous_endpoint_reference": previous_endpoint_reference,
        "new_endpoint": new_endpoint,
        "gateway_deployment_id": gateway_deployment_id,
        "authority_mode": authority_mode,
        "previous_policy_version": previous_policy_version,
        "policy_version": G13_OPERATOR_RECOVERY_POLICY_VERSION,
        "source_event_ids": source_ids,
        "canary_budget_usdc": f"{Decimal(canary_budget_usdc):.6f}",
        "canary_execution_limit": 1,
        "created_at": _iso(instant),
    }
    payload = {**material, "canonical_hash": canonical_hash(material)}
    if not validate_recovery_payload(payload):
        raise ValueError("G13_RECOVERY_EVENT_INVALID")
    event_id = recovery_event_id(payload)
    existing = session.get(UsageEvent, event_id)
    if existing is not None:
        if existing.event_type != G13_RECOVERY_EVENT_TYPE or existing.metadata_ != payload:
            raise ValueError("G13_RECOVERY_EVENT_CONFLICT")
        _activate_policy_binding_for_recovery(session, existing)
        return existing
    event = UsageEvent(
        event_id=event_id,
        mandate_id=None,
        event_type=G13_RECOVERY_EVENT_TYPE,
        metadata_=payload,
        created_at=instant,
    )
    session.add(event)
    session.flush()
    _activate_policy_binding_for_recovery(session, event)
    return event


def record_review_recovery(
    session: Session,
    *,
    agent_identity_id: str,
    source_policy_evaluation_id: str,
    source_event_ids: Iterable[str],
    created_at: datetime | None = None,
) -> UsageEvent:
    """Authorize one bounded probe after reviewed, reconciled external failures."""

    from app.domain.mandates import PolicyEvaluation

    source_evaluation = session.get(PolicyEvaluation, source_policy_evaluation_id)
    if (
        source_evaluation is None
        or source_evaluation.policy_subject_id != agent_identity_id
        or source_evaluation.policy_version != G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION
        or source_evaluation.result != "REVIEW"
    ):
        raise ValueError("G13_REVIEW_RECOVERY_EVALUATION_INVALID")
    source_ids = sorted(set(str(value) for value in source_event_ids))
    source_events = session.query(UsageEvent).filter(UsageEvent.event_id.in_(source_ids)).all()
    if (
        not source_ids
        or {event.event_id for event in source_events} != set(source_ids)
        or any(
            event.event_type != "ACQUISITION_PAYMENT_RECONCILED"
            or (event.metadata_ or {}).get("settled") is not False
            for event in source_events
        )
    ):
        raise ValueError("G13_REVIEW_RECOVERY_SOURCE_INVALID")

    instant = created_at or datetime.now(timezone.utc)
    material = {
        "schema_version": G13_REVIEW_RECOVERY_SCHEMA_VERSION,
        "agent_identity_id": agent_identity_id,
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_REASON,
        "previous_policy_version": G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION,
        "policy_version": G13_REVIEW_RECOVERY_POLICY_VERSION,
        "source_policy_evaluation_id": source_policy_evaluation_id,
        "source_event_ids": source_ids,
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": _iso(instant),
    }
    payload = {**material, "canonical_hash": canonical_hash(material)}
    if not validate_recovery_payload(payload):
        raise ValueError("G13_REVIEW_RECOVERY_EVENT_INVALID")
    event_id = recovery_event_id(payload)
    existing = session.get(UsageEvent, event_id)
    if existing is not None:
        if existing.event_type != G13_RECOVERY_EVENT_TYPE or existing.metadata_ != payload:
            raise ValueError("G13_REVIEW_RECOVERY_EVENT_CONFLICT")
        _activate_policy_binding_for_recovery(session, existing)
        return existing
    event = UsageEvent(
        event_id=event_id,
        mandate_id=None,
        event_type=G13_RECOVERY_EVENT_TYPE,
        metadata_=payload,
        created_at=instant,
    )
    session.add(event)
    session.flush()
    _activate_policy_binding_for_recovery(session, event)
    return event


def record_review_recovery_v2(
    session: Session,
    *,
    agent_identity_id: str,
    source_policy_evaluation_id: str,
    source_event_ids: Iterable[str],
    created_at: datetime | None = None,
) -> UsageEvent:
    """Authorize one bounded probe on the v0.4 -> v0.5 transition.

    Precondition: the source policy evaluation is a real v0.4 REVIEW whose
    sole_blocker is G13_EXTERNAL_ACQUISITION_RECURRENCE.  The episode ids
    carried in the recovery payload are exactly those the source evaluation
    `result_core.external_failure_episode_ids` already attributed to the
    blocker, preserving the causal audit chain:
      external episodes -> v0.4 REVIEW -> recovery v0.5 -> post-cutoff window.
    No historical observation or event row is mutated or deleted; the cutoff
    is applied by downstream readers filtering on `created_at`.
    """

    from app.domain.mandates import PolicyEvaluation

    source_evaluation = session.get(PolicyEvaluation, source_policy_evaluation_id)
    if (
        source_evaluation is None
        or source_evaluation.policy_subject_id != agent_identity_id
        or source_evaluation.policy_version != G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION
        or source_evaluation.result != "REVIEW"
    ):
        raise ValueError("G13_REVIEW_RECOVERY_EVALUATION_INVALID")
    result_core = dict(source_evaluation.result_core or {})
    if result_core.get("sole_blocker") != G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER:
        raise ValueError("G13_REVIEW_RECOVERY_EVALUATION_INVALID")
    source_episode_ids = tuple(sorted({
        str(value) for value in (result_core.get("external_failure_episode_ids") or ())
        if value
    }))
    if not source_episode_ids:
        raise ValueError("G13_REVIEW_RECOVERY_EVALUATION_INVALID")
    source_ids = sorted(set(str(value) for value in source_event_ids))
    source_events = session.query(UsageEvent).filter(UsageEvent.event_id.in_(source_ids)).all()
    if (
        not source_ids
        or {event.event_id for event in source_events} != set(source_ids)
        or any(
            event.event_type != "ACQUISITION_PAYMENT_RECONCILED"
            or (event.metadata_ or {}).get("settled") is not False
            for event in source_events
        )
    ):
        raise ValueError("G13_REVIEW_RECOVERY_SOURCE_INVALID")

    instant = created_at or datetime.now(timezone.utc)
    material = {
        "schema_version": G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION,
        "agent_identity_id": agent_identity_id,
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_V2_REASON,
        "previous_policy_version": G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION,
        "policy_version": G13_REVIEW_RECOVERY_V2_POLICY_VERSION,
        "source_policy_evaluation_id": source_policy_evaluation_id,
        "source_event_ids": source_ids,
        "source_failure_episode_ids": sorted(set(str(v) for v in source_episode_ids)),
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": _iso(instant),
    }
    payload = {**material, "canonical_hash": canonical_hash(material)}
    if not _validate_review_recovery_v2_payload(payload):
        raise ValueError("G13_REVIEW_RECOVERY_EVENT_INVALID")
    event_id = recovery_event_id(payload)
    existing = session.get(UsageEvent, event_id)
    if existing is not None:
        if existing.event_type != G13_RECOVERY_EVENT_TYPE or existing.metadata_ != payload:
            raise ValueError("G13_REVIEW_RECOVERY_EVENT_CONFLICT")
        _activate_policy_binding_for_recovery(session, existing)
        return existing
    event = UsageEvent(
        event_id=event_id,
        mandate_id=None,
        event_type=G13_RECOVERY_EVENT_TYPE,
        metadata_=payload,
        created_at=instant,
    )
    session.add(event)
    session.flush()
    _activate_policy_binding_for_recovery(session, event)
    return event


def record_current_review_recovery(
    session: Session,
    *,
    agent_identity_id: str,
    source_policy_evaluation_id: str,
    source_event_ids: Iterable[str],
    created_at: datetime | None = None,
) -> UsageEvent:
    """Authorize one bounded probe while retaining G13 v0.4.

    The source evaluation and durable binding are checked canonically. This
    records a recovery contract event, but deliberately does not transition
    the policy binding or alter any historical observation/failure row.
    """

    from app.domain.mandates import PolicyEvaluation
    from app.authority.binding import current_g13_policy_binding

    source_evaluation = session.get(PolicyEvaluation, source_policy_evaluation_id)
    binding = current_g13_policy_binding(session, agent_identity_id)
    if (
        source_evaluation is None
        or binding is None
        or source_evaluation.policy_subject_id != agent_identity_id
        or source_evaluation.policy_version != G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION
        or source_evaluation.result != "REVIEW"
        or source_evaluation.policy_binding_id != binding.binding_id
        or source_evaluation.policy_binding_hash != binding.canonical_hash
        or binding.effective_policy_version != G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION
    ):
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_EVALUATION_INVALID")
    result_core = dict(source_evaluation.result_core or {})
    if result_core.get("sole_blocker") != G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER:
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_EVALUATION_INVALID")
    episode_ids = sorted({str(value) for value in (result_core.get("external_failure_episode_ids") or ()) if value})
    if not episode_ids:
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_EVALUATION_INVALID")
    source_ids = sorted(set(str(value) for value in source_event_ids))
    source_events = session.query(UsageEvent).filter(UsageEvent.event_id.in_(source_ids)).all()
    if (
        not source_ids
        or {event.event_id for event in source_events} != set(source_ids)
        or any(not _economically_reconciled_terminal(session, event) for event in source_events)
    ):
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_SOURCE_INVALID")
    source_episode_ids = {
        str((event.metadata_ or {}).get("failure_episode_id"))
        for event in source_events
        if (event.metadata_ or {}).get("failure_episode_id")
    }
    if source_episode_ids != set(episode_ids):
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_SOURCE_INCOMPLETE")

    instant = created_at or datetime.now(timezone.utc)
    material = {
        "schema_version": G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION,
        "recovery_contract_version": G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION,
        "agent_identity_id": agent_identity_id,
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_CURRENT_REASON,
        "policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION,
        "source_policy_evaluation_id": source_policy_evaluation_id,
        "source_policy_binding_id": binding.binding_id,
        "source_policy_binding_hash": binding.canonical_hash,
        "source_event_ids": source_ids,
        "source_failure_episode_ids": episode_ids,
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": _iso(instant),
    }
    payload = {**material, "canonical_hash": canonical_hash(material)}
    if not _validate_current_review_recovery_payload(payload):
        raise ValueError("G13_CURRENT_REVIEW_RECOVERY_EVENT_INVALID")
    event_id = recovery_event_id(payload)
    existing = session.get(UsageEvent, event_id)
    if existing is not None:
        if existing.event_type != G13_RECOVERY_EVENT_TYPE or existing.metadata_ != payload:
            raise ValueError("G13_CURRENT_REVIEW_RECOVERY_EVENT_CONFLICT")
        if _recovery_event_consumed(session, existing):
            raise ValueError("G13_CURRENT_REVIEW_RECOVERY_ALREADY_CONSUMED")
        return existing
    event = UsageEvent(
        event_id=event_id,
        mandate_id=None,
        event_type=G13_RECOVERY_EVENT_TYPE,
        metadata_=payload,
        created_at=instant,
    )
    session.add(event)
    session.flush()
    # Same-policy recovery must preserve the existing durable binding.
    return event


def _reservation_terminal_for_reconciliation(session: Session, event: UsageEvent, *, settled: bool, amount: Decimal) -> bool:
    """Check the durable G12 reservation state behind one reconciliation.

    Reconciliation is terminal only when the economic side effect is closed:
    no-payment events have no remaining reservation, while confirmed payments
    have a closed reservation whose actual spend equals the settled amount.
    """
    if not event.mandate_id:
        return False
    reservation = session.get(PublicManualSpendReservation, event.mandate_id)
    if reservation is None:
        return False
    reserved = Decimal(str(reservation.reserved_usdc or 0))
    actual = Decimal(str(reservation.actual_spend_usdc or 0))
    if reserved != Decimal("0"):
        return False
    if settled:
        return reservation.status == "SETTLED" and actual == amount
    return reservation.status in {"SETTLED", "RELEASED"} and actual == Decimal("0")


def _economically_reconciled_terminal(session: Session, event: UsageEvent) -> bool:
    """Return true only for a complete, terminal economic reconciliation."""
    if event.event_type != "ACQUISITION_PAYMENT_RECONCILED":
        return False
    metadata = event.metadata_ or {}
    settled = metadata.get("settled")
    try:
        settled_usdc = Decimal(str(metadata.get("settled_usdc", "-1")))
        actual_cost = Decimal(str(metadata.get("actual_cost_usdc", "-1")))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not settled:
        return (
            settled is False
            and settled_usdc == Decimal("0")
            and actual_cost == Decimal("0")
            and _reservation_terminal_for_reconciliation(session, event, settled=False, amount=Decimal("0"))
        )
    if settled is not True:
        return False
    tx_hash = metadata.get("transaction_hash") or metadata.get("tx_hash")
    return (
        metadata.get("payment_state") == "PAYMENT_CONFIRMED"
        and isinstance(tx_hash, str)
        and bool(tx_hash.strip())
        and settled_usdc > Decimal("0")
        and actual_cost == settled_usdc
        and _reservation_terminal_for_reconciliation(session, event, settled=True, amount=settled_usdc)
    )


def _recovery_event_consumed(session: Session, event: UsageEvent) -> bool:
    """A recovery event is single-use once its probe has been started."""
    if not hasattr(session, "query"):
        return False
    rows = session.query(UsageEvent).filter_by(event_type="G13_RECOVERY_PROBE_STARTED").all()
    return any((row.metadata_ or {}).get("recovery_event_id") == event.event_id for row in rows)


def latest_operator_recovery(session: Session, agent_identity_id: str) -> UsageEvent | None:
    events = (
        session.query(UsageEvent)
        .filter_by(event_type=G13_RECOVERY_EVENT_TYPE)
        .order_by(UsageEvent.created_at.desc(), UsageEvent.event_id.desc())
        .all()
    )
    for event in events:
        payload = event.metadata_ or {}
        if payload.get("agent_identity_id") != agent_identity_id:
            continue
        if (
            event.mandate_id is not None
            or not validate_recovery_payload(payload)
            or recovery_event_id(payload) != event.event_id
            or _iso(event.created_at) != payload.get("created_at")
        ):
            raise ValueError("G13_RECOVERY_EVENT_HASH_INVALID")
        return event
    return None


def latest_recovery_for_binding(session: Session, agent_identity_id: str, binding: Any) -> UsageEvent | None:
    """Find recovery context without using it to select the policy version."""

    events = (
        session.query(UsageEvent)
        .filter_by(event_type=G13_RECOVERY_EVENT_TYPE)
        .order_by(UsageEvent.created_at.desc(), UsageEvent.event_id.desc())
        .all()
    )
    for event in events:
        payload = event.metadata_ or {}
        if payload.get("agent_identity_id") != agent_identity_id:
            continue
        if not validate_recovery_payload(payload) or recovery_event_id(payload) != event.event_id:
            continue
        if payload.get("source_policy_binding_id") == binding.binding_id and payload.get("policy_version") == binding.effective_policy_version:
            return event
        if event.event_id == binding.recovery_event_id:
            return event
    return None


__all__ = [
    "G13_OPERATOR_RECOVERY_POLICY_ID",
    "G13_OPERATOR_RECOVERY_POLICY_VERSION",
    "G13_OPERATOR_RECOVERY_ENDPOINT",
    "G13_OPERATOR_RECOVERY_FAILURE_RULES",
    "G13_OPERATOR_RECOVERY_PREVIOUS_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_POLICY_ID",
    "G13_REVIEW_RECOVERY_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_REASON",
    "G13_REVIEW_RECOVERY_SCHEMA_VERSION",
    "G13_REVIEW_RECOVERY_V2_POLICY_ID",
    "G13_REVIEW_RECOVERY_V2_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_V2_REASON",
    "G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION",
    "G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER",
    "G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION",
    "G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION",
    "G13_REVIEW_RECOVERY_CURRENT_REASON",
    "G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION",
    "G13_RECOVERY_EVENT_TYPE",
    "latest_operator_recovery",
    "record_operator_recovery",
    "record_review_recovery",
    "record_review_recovery_v2",
    "record_current_review_recovery",
    "latest_recovery_for_binding",
    "validate_recovery_payload",
]
