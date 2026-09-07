"""Delegated autonomy authority and one-shot permits.

This module is intentionally independent from the epistemic Decision Gate:
G12, G13 and the AuthorityProfile must all agree before an external action.
"""
from datetime import datetime, timezone
from decimal import Decimal
import os

from sqlalchemy.exc import IntegrityError

from app.domain.mandates import AgentAuthorityProfile, AgentIdentity, ExecutionPermit, Mandate, UsageEvent
from app.pramagraph.evaluation import digest

FULL_AUTONOMY_FLAG = "FULL_AUTONOMY_ENABLED"
AUTONOMY_STATES = {"ACTIVE", "THROTTLED", "REVIEW_REQUIRED", "HALTED"}


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
    at = at or now()
    profiles = session.query(AgentAuthorityProfile).filter(
        AgentAuthorityProfile.agent_identity_id == identity_id,
        AgentAuthorityProfile.status == "ACTIVE",
        AgentAuthorityProfile.valid_from <= at,
    ).all()
    profiles = [p for p in profiles if p.valid_until is None or p.valid_until > at]
    if len(profiles) != 1:
        raise ValueError("AUTHORITY_PROFILE_AMBIGUOUS" if len(profiles) > 1 else "AUTHORITY_PROFILE_MISSING")
    return profiles[0]


def _allowed(profile, action_kind, intent=None):
    if profile.allowed_action_kinds and action_kind not in profile.allowed_action_kinds:
        return False
    if intent and profile.allowed_intents and intent not in profile.allowed_intents:
        return False
    if not profile.external_execution_allowed or action_kind.startswith("TELEGRAPH") and not profile.telegraph_allowed:
        return False
    return True


def g12_check(profile, amount: Decimal) -> tuple[bool, str]:
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
                           intent: str | None = None, at: datetime | None = None) -> ExecutionPermit:
    identity_id = mandate.agent_identity_id
    if not identity_id or not full_autonomy_enabled(identity_id):
        raise ValueError("FULL_AUTONOMY_DISABLED")
    profile = resolve_profile(session, identity_id, at)
    identity = session.get(AgentIdentity, identity_id)
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    if identity.autonomy_state == "HALTED":
        raise ValueError("G13_HALT")
    if identity.autonomy_state == "REVIEW_REQUIRED":
        raise ValueError("G13_REVIEW")
    if profile.status != "ACTIVE" or not _allowed(profile, action_kind, intent):
        raise ValueError("AUTHORITY_ACTION_NOT_ALLOWED")
    allowed, g12_result = g12_check(profile, Decimal(amount))
    if not allowed:
        raise ValueError(g12_result)
    if g13_result == "HALT": raise ValueError("G13_HALT")
    if g13_result == "REVIEW": raise ValueError("G13_REVIEW")
    if g13_result == "THROTTLE" and not (constraints or {}).get("throttle_satisfied"):
        raise ValueError("G13_THROTTLE_CONSTRAINTS_REQUIRED")
    existing = session.query(ExecutionPermit).filter_by(action_id=action_id).one_or_none()
    if existing:
        return existing
    issued = at or now()
    material = {
        "principal_id": profile.principal_id, "agent_identity_id": identity_id,
        "mandate_id": mandate.mandate_id, "action_id": action_id,
        "action_kind": action_kind, "authority_profile_id": profile.authority_profile_id,
        "g12_result": "PERMIT", "g13_result": g13_result,
        "decision_id": decision_id, "constraints": constraints or {},
    }
    permit = ExecutionPermit(**material, authority_hash=digest(material), issued_at=issued)
    session.add(permit)
    session.flush()
    session.add(UsageEvent(mandate_id=mandate.mandate_id, event_type="EXECUTION_PERMIT_ISSUED", metadata_={
        "append_only": True, "schema_version": "delegated-autonomy-v1", "permit_id": permit.permit_id,
        "principal_id": profile.principal_id, "agent_identity_id": identity_id,
        "action_id": action_id, "authority_hash": permit.authority_hash,
    }))
    return permit


def consume_execution_permit(session, permit_id: str, *, result_hash: str | None = None) -> ExecutionPermit:
    permit = session.query(ExecutionPermit).filter_by(permit_id=permit_id).with_for_update().one_or_none()
    if permit is None: raise ValueError("EXECUTION_PERMIT_MISSING")
    if permit.consumed_at is not None: raise ValueError("EXECUTION_PERMIT_ALREADY_CONSUMED")
    if permit.expires_at is not None and permit.expires_at <= now(): raise ValueError("EXECUTION_PERMIT_EXPIRED")
    permit.consumed_at = now()
    permit.result_hash = result_hash
    session.add(UsageEvent(mandate_id=permit.mandate_id, event_type="EXECUTION_PERMIT_CONSUMED", metadata_={
        "append_only": True, "schema_version": "delegated-autonomy-v1", "permit_id": permit.permit_id,
        "agent_identity_id": permit.agent_identity_id, "action_id": permit.action_id,
        "result_hash": result_hash,
    }))
    return permit
