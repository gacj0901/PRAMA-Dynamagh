"""Append-only, canonically hashed operator recovery transitions for G13."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import uuid
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from app.domain.mandates import UsageEvent
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


def validate_recovery_payload(payload: Mapping[str, Any]) -> bool:
    return _validate_endpoint_recovery_payload(payload) or _validate_review_recovery_payload(payload)


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
    return event


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


__all__ = [
    "G13_OPERATOR_RECOVERY_POLICY_ID",
    "G13_OPERATOR_RECOVERY_POLICY_VERSION",
    "G13_OPERATOR_RECOVERY_ENDPOINT",
    "G13_OPERATOR_RECOVERY_FAILURE_RULES",
    "G13_OPERATOR_RECOVERY_PREVIOUS_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_POLICY_ID",
    "G13_REVIEW_RECOVERY_POLICY_VERSION",
    "G13_REVIEW_RECOVERY_SCHEMA_VERSION",
    "G13_REVIEW_RECOVERY_REASON",
    "G13_RECOVERY_EVENT_TYPE",
    "latest_operator_recovery",
    "record_operator_recovery",
    "record_review_recovery",
    "validate_recovery_payload",
]
