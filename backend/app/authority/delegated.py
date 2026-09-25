"""Delegated autonomy authority and one-shot permits.

This module is intentionally independent from the epistemic Decision Gate:
G12, G13 and the AuthorityProfile must all agree before an external action.
"""
from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Mapping
import os

from sqlalchemy.exc import IntegrityError

from app.domain.mandates import AgentAuthorityProfile, AgentIdentity, ExecutionPermit, Mandate, UsageEvent
from app.epistemic.contracts import canonical_hash
from app.authority.profiles import AuthorityResolutionError, get_effective_authority_profile

FULL_AUTONOMY_FLAG = "FULL_AUTONOMY_ENABLED"
AUTONOMY_STATES = {"ACTIVE", "THROTTLED", "REVIEW_REQUIRED", "HALTED"}
EXECUTION_ACTION_CONTRACT = "execution-action-envelope-v1"
EXECUTION_PERMIT_CONTRACT = "execution-permit-authority-v1"
ACTION_ENVELOPE_CONSTRAINT = "execution_action_envelope"
EXECUTION_COMMITMENT_LOCK_ORDER = (
    "execution_permit",
    "mandate",
    "acquisition_task",
    "agent_identity",
    "public_manual_spend_reservation",
    "authority_profile",
    "user_credit_account",
    "bootstrap_authority",
)


def now():
    return datetime.now(timezone.utc)


def full_autonomy_enabled(agent_id: str | None = None) -> bool:
    if os.environ.get(FULL_AUTONOMY_FLAG, "false").lower() != "true":
        return False
    allowlist = {value.strip() for value in os.environ.get("FULL_AUTONOMY_AGENT_ALLOWLIST", "").split(",") if value.strip()}
    return not allowlist or bool(agent_id and agent_id in allowlist)


def resolve_unambiguous_identity(session, context_id: str) -> AgentIdentity:
    identities = session.query(AgentIdentity).filter_by(m2m_context_id=context_id, status="ACTIVE").all()
    if len(identities) != 1:
        raise ValueError("AMBIGUOUS_AGENT_AUTHORITY")
    if identities[0].autonomy_state == "HALTED":
        raise ValueError("AGENT_AUTONOMY_HALTED")
    if identities[0].autonomy_state == "REVIEW_REQUIRED":
        raise ValueError("AGENT_AUTONOMY_REVIEW_REQUIRED")
    return identities[0]


def resolve_profile(session, identity_id: str, at: datetime | None = None) -> AgentAuthorityProfile:
    try:
        return get_effective_authority_profile(session, identity_id, at or now())
    except AuthorityResolutionError as error:
        mapping = {
            "NO_AUTHORITY_PROFILE": "AUTHORITY_PROFILE_MISSING",
            "AMBIGUOUS_AUTHORITY_PROFILE": "AUTHORITY_PROFILE_AMBIGUOUS",
        }
        raise ValueError(mapping.get(error.code, error.code)) from error


def _allowed(profile, action_kind, intent=None):
    if profile.allowed_action_kinds and action_kind not in profile.allowed_action_kinds:
        return False
    if intent and profile.allowed_intents and intent not in profile.allowed_intents:
        return False
    if not profile.external_execution_allowed or action_kind.startswith("TELEGRAPH") and not profile.telegraph_allowed:
        return False
    return True


def _canonical_action_value(value):
    """Convert supported action values into stable JSON values.

    Strings, including query text, are preserved byte-for-byte at the Python
    string boundary. Decimal formatting is normalized without float coercion.
    """
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("EXECUTION_PERMIT_INVALID")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, float):
        raise ValueError("EXECUTION_PERMIT_INVALID")
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("EXECUTION_PERMIT_INVALID")
        return {key: _canonical_action_value(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_action_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError("EXECUTION_PERMIT_INVALID")


def build_execution_action_material(
    *, mandate_id: str, agent_identity_id: str, action_id: str,
    action_kind: str, query: str, requested_intent: str | None,
    causal_request_id: str, amount: Decimal, adapter_target: Mapping,
    reservation: Mapping,
) -> dict:
    """Build the provider-neutral, deterministic action envelope."""
    if not isinstance(query, str):
        raise ValueError("EXECUTION_PERMIT_INVALID")
    payload = {
        "query": query,
        "requested_intent": requested_intent,
        "causal_request_id": causal_request_id,
    }
    return _canonical_action_value({
        "contract": EXECUTION_ACTION_CONTRACT,
        "mandate_id": mandate_id,
        "agent_identity_id": agent_identity_id,
        "action_id": action_id,
        "action_kind": action_kind,
        "payload_hash": canonical_hash(_canonical_action_value(payload)),
        "target": adapter_target,
        "economic_envelope": {
            "authorized_amount_usdc": amount,
            "reservation": reservation,
        },
    })


def build_execution_permit_material(
    *, principal_id, agent_identity_id, mandate_id, action_id, action_kind,
    authority_profile_id, g12_result, g13_result, decision_id, constraints,
) -> dict:
    """Single canonical serialization source for issue and consume hashes."""
    return _canonical_action_value({
        "contract": EXECUTION_PERMIT_CONTRACT,
        "principal_id": principal_id,
        "agent_identity_id": agent_identity_id,
        "mandate_id": mandate_id,
        "action_id": action_id,
        "action_kind": action_kind,
        "authority_profile_id": authority_profile_id,
        "g12_result": g12_result,
        "g13_result": g13_result,
        "decision_id": decision_id,
        "constraints": constraints,
    })


def _permit_material_from_row(permit) -> dict:
    return build_execution_permit_material(
        principal_id=permit.principal_id,
        agent_identity_id=permit.agent_identity_id,
        mandate_id=permit.mandate_id,
        action_id=permit.action_id,
        action_kind=permit.action_kind,
        authority_profile_id=permit.authority_profile_id,
        g12_result=permit.g12_result,
        g13_result=permit.g13_result,
        decision_id=permit.decision_id,
        constraints=permit.constraints,
    )


def _validate_action_match(stored: dict, expected: dict) -> None:
    if not isinstance(stored, dict) or stored.get("contract") != EXECUTION_ACTION_CONTRACT:
        raise ValueError("EXECUTION_PERMIT_INVALID")
    if stored.get("payload_hash") != expected.get("payload_hash"):
        raise ValueError("EXECUTION_PERMIT_PAYLOAD_MISMATCH")
    if stored.get("target") != expected.get("target"):
        raise ValueError("EXECUTION_PERMIT_TARGET_MISMATCH")
    if stored.get("economic_envelope") != expected.get("economic_envelope"):
        raise ValueError("EXECUTION_PERMIT_ECONOMIC_MISMATCH")
    if canonical_hash(stored) != canonical_hash(expected):
        raise ValueError("EXECUTION_PERMIT_ACTION_MISMATCH")


def g12_check(profile, amount: Decimal, *, reservation_verified: bool = False) -> tuple[bool, str]:
    if not reservation_verified:
        return False, "G12_RESERVATION_REQUIRED"
    if profile.unlimited_budget:
        # The profile adds no economic cap; the numeric G12 reservation binds.
        return True, "PERMIT"
    if profile.economic_budget is None or Decimal(profile.economic_budget) <= 0:
        return False, "G12_NO_DELEGATED_ECONOMIC_AUTHORITY"
    if profile.per_action_budget is not None and amount > Decimal(profile.per_action_budget):
        return False, "G12_PER_ACTION_BUDGET_EXCEEDED"
    if amount > Decimal(profile.economic_budget):
        return False, "G12_DELEGATED_BUDGET_EXCEEDED"
    return True, "PERMIT"


def issue_execution_permit(session, *, mandate: Mandate, action_id: str, action_kind: str,
                           amount: Decimal, g13_result: str = "CONTINUE",
                           decision_id: str | None = None, constraints: dict | None = None,
                           action_material: dict, intent: str | None = None,
                           at: datetime | None = None) -> ExecutionPermit:
    identity_id = mandate.agent_identity_id
    if not identity_id or not full_autonomy_enabled(identity_id):
        raise ValueError("FULL_AUTONOMY_DISABLED")
    profile = resolve_profile(session, identity_id, at)
    identity = session.get(AgentIdentity, identity_id)
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    if identity.autonomy_state == "HALTED":
        raise ValueError("G13_HALT")
    recovery_probe = bool((constraints or {}).get("recovery_probe_authorized"))
    bootstrap_authorized = bool((constraints or {}).get("bootstrap_authorized"))
    if identity.autonomy_state == "REVIEW_REQUIRED" and not recovery_probe and not bootstrap_authorized:
        raise ValueError("G13_REVIEW")
    if profile.status != "ACTIVE" or not _allowed(profile, action_kind, intent):
        raise ValueError("AUTHORITY_ACTION_NOT_ALLOWED")
    allowed, g12_result = g12_check(
        profile,
        Decimal(amount),
        reservation_verified=bool((constraints or {}).get("g12_reservation_verified")),
    )
    if not allowed:
        raise ValueError(g12_result)
    if g13_result == "HALT": raise ValueError("G13_HALT")
    if g13_result == "REVIEW" and not recovery_probe and not bootstrap_authorized: raise ValueError("G13_REVIEW")
    if g13_result == "THROTTLE" and not (constraints or {}).get("throttle_satisfied"):
        raise ValueError("G13_THROTTLE_CONSTRAINTS_REQUIRED")
    existing = session.query(ExecutionPermit).filter_by(action_id=action_id).one_or_none()
    if existing:
        return existing
    issued = at or now()
    permit_constraints = {
        **(constraints or {}),
        "agent_autonomy_state": identity.autonomy_state,
        ACTION_ENVELOPE_CONSTRAINT: _canonical_action_value(action_material),
    }
    material = {
        "principal_id": profile.principal_id, "agent_identity_id": identity_id,
        "mandate_id": mandate.mandate_id, "action_id": action_id,
        "action_kind": action_kind, "authority_profile_id": profile.authority_profile_id,
        "g12_result": "PERMIT", "g13_result": g13_result,
        "decision_id": decision_id, "constraints": permit_constraints,
    }
    permit = ExecutionPermit(
        **material,
        authority_hash=canonical_hash(build_execution_permit_material(**material)),
        issued_at=issued,
    )
    session.add(permit)
    session.flush()
    session.add(UsageEvent(mandate_id=mandate.mandate_id, event_type="EXECUTION_PERMIT_ISSUED", metadata_={
        "append_only": True, "schema_version": "delegated-autonomy-v1", "permit_id": permit.permit_id,
        "principal_id": profile.principal_id, "agent_identity_id": identity_id,
        "action_id": action_id, "authority_hash": permit.authority_hash,
    }))
    return permit


def consume_execution_permit(
    session, permit_id: str, *, expected_action_material: dict,
    authority_validator, result_hash: str | None = None,
) -> ExecutionPermit:
    """Commit one exact action for dispatch under the one-shot permit lock.

    The caller's transaction is the Execution Commitment Point: the bound
    action, fresh revocable authority, and one-shot permit are checked and
    durably recorded together. ``authority_validator`` performs only local
    DB/policy work; the caller commits before opening the external connection.
    """
    permit = session.query(ExecutionPermit).populate_existing().filter_by(permit_id=permit_id).with_for_update().one_or_none()
    if permit is None: raise ValueError("EXECUTION_PERMIT_MISSING")
    if permit.consumed_at is not None: raise ValueError("EXECUTION_PERMIT_ALREADY_CONSUMED")
    if permit.expires_at is not None and permit.expires_at <= now(): raise ValueError("EXECUTION_PERMIT_EXPIRED")
    stored_action = (permit.constraints or {}).get(ACTION_ENVELOPE_CONSTRAINT)
    if not permit.authority_hash or canonical_hash(_permit_material_from_row(permit)) != permit.authority_hash:
        raise ValueError("EXECUTION_PERMIT_INVALID")
    _validate_action_match(stored_action, _canonical_action_value(expected_action_material))
    authority_validator(permit)
    committed_at = now()
    permit.consumed_at = committed_at
    permit.result_hash = result_hash
    session.add(UsageEvent(mandate_id=permit.mandate_id, event_type="EXECUTION_PERMIT_CONSUMED", metadata_={
        "append_only": True, "schema_version": "delegated-autonomy-v1", "permit_id": permit.permit_id,
        "agent_identity_id": permit.agent_identity_id, "action_id": permit.action_id,
        "result_hash": result_hash,
    }))
    session.add(UsageEvent(
        mandate_id=permit.mandate_id,
        event_type="EXECUTION_DISPATCH_COMMITTED",
        metadata_={
            "append_only": True,
            "schema_version": "execution-commitment-v1",
            "commitment_state": "COMMITTED_FOR_DISPATCH",
            "permit_id": permit.permit_id,
            "action_id": permit.action_id,
            "agent_identity_id": permit.agent_identity_id,
            "committed_at": committed_at.isoformat(),
            "authority_hash": permit.authority_hash,
            "action_envelope_hash": canonical_hash(stored_action),
        },
    ))
    return permit
