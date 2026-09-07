"""Principal-owned authority profiles and permit inspection."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.m2m import require_m2m_auth
from app.authority.delegated import resolve_unambiguous_identity
from app.domain.mandates import AgentAuthorityProfile, ExecutionPermit
from app.persistence.database import get_session

router = APIRouter(prefix="/v1/authority", tags=["delegated-authority"])


class AuthorityProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: str = Field(min_length=1, max_length=255)
    allowed_intents: list[str] = Field(default_factory=list, max_length=100)
    allowed_action_kinds: list[str] = Field(default_factory=list, max_length=100)
    economic_budget: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    per_action_budget: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    rolling_budget: dict[str, Any] | None = None
    concurrency_limit: int | None = Field(default=None, ge=1)
    cadence_policy: dict[str, Any] | None = None
    external_execution_allowed: bool = False
    telegraph_allowed: bool = False
    anchoring_allowed: bool = False
    erc8183_allowed: bool = False
    human_review_thresholds: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = "agent-authority-v0"
    valid_until: datetime | None = None


def _read(profile):
    return {key: getattr(profile, key) for key in ("authority_profile_id", "principal_id", "agent_identity_id", "status", "valid_from", "valid_until", "allowed_intents", "allowed_action_kinds", "economic_budget", "per_action_budget", "rolling_budget", "concurrency_limit", "cadence_policy", "external_execution_allowed", "telegraph_allowed", "anchoring_allowed", "erc8183_allowed", "human_review_thresholds", "policy_version", "created_at", "updated_at")}


@router.post("/profiles", status_code=201)
def create_profile(payload: AuthorityProfileInput, session: Session = Depends(get_session), context_id: str = Depends(require_m2m_auth)):
    try:
        identity = resolve_unambiguous_identity(session, context_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    if payload.valid_until and payload.valid_until <= datetime.now(timezone.utc):
        raise HTTPException(422, "AUTHORITY_PROFILE_ALREADY_EXPIRED")
    profile = AgentAuthorityProfile(agent_identity_id=identity.agent_id, status="ACTIVE", valid_from=datetime.now(timezone.utc), **payload.model_dump())
    session.add(profile)
    session.commit(); session.refresh(profile)
    session.add(__import__("app.domain.mandates", fromlist=["UsageEvent"]).UsageEvent(event_type="AUTHORITY_PROFILE_ISSUED", metadata_={"append_only": True, "schema_version": "delegated-autonomy-v1", "authority_profile_id": profile.authority_profile_id, "principal_id": profile.principal_id, "agent_identity_id": identity.agent_id}))
    session.commit()
    return _read(profile)


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
