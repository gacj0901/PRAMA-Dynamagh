"""Principal-owned authority profiles and permit inspection."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.m2m import require_m2m_auth
from app.authority.delegated import resolve_unambiguous_identity
from app.domain.mandates import AgentAuthorityProfile, ExecutionPermit
from app.persistence.database import get_session

router = APIRouter(prefix="/v1/authority", tags=["delegated-authority"])


def _read(profile):
    return {key: getattr(profile, key) for key in ("authority_profile_id", "principal_id", "agent_identity_id", "status", "valid_from", "valid_until", "allowed_intents", "allowed_action_kinds", "economic_budget", "per_action_budget", "rolling_budget", "concurrency_limit", "cadence_policy", "external_execution_allowed", "telegraph_allowed", "anchoring_allowed", "erc8183_allowed", "human_review_thresholds", "unlimited_budget", "unlimited_execution_rate", "policy_version", "created_at", "updated_at")}


# AUTHORITY_WRITE_API_DEFERRED: true. The existing M2M token identifies an
# agent context, not a principal/operator allowed to enlarge that agent's grant.
# Trusted administration lives in app.authority.profiles until a real operator
# write authorization surface exists. Keep only the existing scoped reads.


@router.get("/profiles")
def list_profiles(session: Session = Depends(get_session), context_id: str = Depends(require_m2m_auth)):
    try: identity = resolve_unambiguous_identity(session, context_id)
    except ValueError as error: raise HTTPException(409, str(error)) from error
    return [_read(p) for p in session.query(AgentAuthorityProfile).filter_by(agent_identity_id=identity.agent_id).order_by(AgentAuthorityProfile.created_at)]


@router.get("/permits/{permit_id}")
def get_permit(permit_id: str, session: Session = Depends(get_session), context_id: str = Depends(require_m2m_auth)):
    try: identity = resolve_unambiguous_identity(session, context_id)
    except ValueError as error: raise HTTPException(409, str(error)) from error
    permit = session.get(ExecutionPermit, permit_id)
    if permit is None or permit.agent_identity_id != identity.agent_id: raise HTTPException(404, "EXECUTION_PERMIT_MISSING")
    return {key: getattr(permit, key) for key in ("permit_id", "principal_id", "agent_identity_id", "mandate_id", "action_id", "action_kind", "authority_profile_id", "g12_result", "g13_result", "decision_id", "constraints", "authority_hash", "issued_at", "expires_at", "consumed_at", "result_hash")}
