"""Durable binding of an agent to its effective G13 policy version."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
import re
from typing import Any

from sqlalchemy.orm import Session

from app.epistemic.contracts import canonical_hash


G13_POLICY_BINDING_SCHEMA_VERSION = "g13-policy-binding-v0.1"
G13_POLICY_BINDING_MISSING = "POLICY_BINDING_MISSING"
G13_POLICY_BINDING_UNSUPPORTED = "POLICY_BINDING_UNSUPPORTED"


def _version_key(value: str) -> tuple[int, int] | None:
    """Return the numeric G13 version key used for monotonic transitions."""

    match = re.search(r"-v(\d+)\.(\d+)(?:$|[-+])", str(value))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("G13_POLICY_BINDING_ACTIVATED_AT_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_binding_material(
    *,
    agent_id: str,
    effective_policy_version: str,
    previous_policy_version: str | None,
    source_transition_type: str,
    source_transition_id: str,
    recovery_event_id: str | None,
    activated_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": G13_POLICY_BINDING_SCHEMA_VERSION,
        "agent_id": agent_id,
        "effective_policy_version": effective_policy_version,
        "previous_policy_version": previous_policy_version,
        "source_transition_type": source_transition_type,
        "source_transition_id": source_transition_id,
        "recovery_event_id": recovery_event_id,
        "activated_at": _iso(activated_at),
    }


def binding_id(material: dict[str, Any]) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"prama-dynamagh:g13-policy-binding:{material['agent_id']}:{material['source_transition_id']}:{material['effective_policy_version']}",
        )
    )


def binding_hash(material: dict[str, Any]) -> str:
    return canonical_hash(material)


def current_g13_policy_binding(session: Session, agent_id: str, *, for_update: bool = False):
    """Return the single durable current binding for ``agent_id``."""

    from app.domain.mandates import G13PolicyBinding

    query = session.query(G13PolicyBinding).filter_by(agent_id=agent_id)
    if for_update:
        query = query.with_for_update()
    return query.one_or_none()


def activate_g13_policy_binding(
    session: Session,
    *,
    agent_id: str,
    effective_policy_version: str,
    previous_policy_version: str | None,
    source_transition_type: str,
    source_transition_id: str,
    recovery_event_id: str | None = None,
    activated_at: datetime | None = None,
):
    """Atomically create or replace the current binding for an authorized transition."""

    from app.domain.mandates import G13PolicyBinding

    instant = activated_at or datetime.now(timezone.utc)
    material = canonical_binding_material(
        agent_id=agent_id,
        effective_policy_version=effective_policy_version,
        previous_policy_version=previous_policy_version,
        source_transition_type=source_transition_type,
        source_transition_id=source_transition_id,
        recovery_event_id=recovery_event_id,
        activated_at=instant,
    )
    current = current_g13_policy_binding(session, agent_id, for_update=True)
    if current is not None:
        if (
            current.effective_policy_version == effective_policy_version
            and current.source_transition_id == source_transition_id
        ):
            return current
        if previous_policy_version != current.effective_policy_version:
            raise ValueError("G13_POLICY_BINDING_TRANSITION_MISMATCH")
        current_key = _version_key(current.effective_policy_version)
        next_key = _version_key(effective_policy_version)
        if (
            current_key is not None
            and next_key is not None
            and next_key < current_key
        ) or (
            current_key is None
            and next_key is None
            and effective_policy_version < current.effective_policy_version
        ):
            raise ValueError("G13_POLICY_BINDING_DOWNGRADE_FORBIDDEN")
        current.binding_id = binding_id(material)
        current.effective_policy_version = effective_policy_version
        current.previous_policy_version = previous_policy_version
        current.source_transition_type = source_transition_type
        current.source_transition_id = source_transition_id
        current.recovery_event_id = recovery_event_id
        current.activated_at = instant
        current.canonical_hash = binding_hash(material)
        session.flush()
        return current

    row = G13PolicyBinding(
        binding_id=binding_id(material),
        agent_id=agent_id,
        effective_policy_version=effective_policy_version,
        previous_policy_version=previous_policy_version,
        source_transition_type=source_transition_type,
        source_transition_id=source_transition_id,
        recovery_event_id=recovery_event_id,
        activated_at=instant,
        canonical_hash=binding_hash(material),
    )
    session.add(row)
    session.flush()
    return row


def binding_provenance(binding: Any) -> dict[str, str | None]:
    return {
        "effective_policy_version": binding.effective_policy_version,
        "policy_binding_id": binding.binding_id,
        "policy_binding_hash": binding.canonical_hash,
        "source_transition_id": binding.source_transition_id,
        "recovery_event_id": binding.recovery_event_id,
    }


def policy_binding_missing_evaluation(agent_id: str, *, reason: str = G13_POLICY_BINDING_MISSING):
    """Build an explicit fail-closed evaluation; never infer v0.2."""

    from app.policy_gate.substrate import PolicyEvaluationCore

    return PolicyEvaluationCore(
        policy_id="G13_POLICY_BINDING",
        policy_version="g13-policy-binding-missing-v0.1",
        policy_type="STRUCTURAL_AUTONOMY",
        policy_subject_type="AGENT_IDENTITY",
        policy_subject_id=agent_id,
        observation_refs=(),
        observation_contract_versions={},
        input_core={"agent_id": agent_id, "error": reason},
        triggered_rule_ids=(reason,),
        result="HALT",
        result_core={
            "autonomy_state": "HALTED",
            "failure_code": reason,
            "fail_closed": True,
        },
    )


__all__ = [
    "G13_POLICY_BINDING_SCHEMA_VERSION",
    "G13_POLICY_BINDING_MISSING",
    "G13_POLICY_BINDING_UNSUPPORTED",
    "activate_g13_policy_binding",
    "binding_hash",
    "binding_id",
    "binding_provenance",
    "canonical_binding_material",
    "current_g13_policy_binding",
    "policy_binding_missing_evaluation",
]
