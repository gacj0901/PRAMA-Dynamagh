"""Narrow authenticated creation and read-only inspection of M2M subjects."""

import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.m2m import require_m2m_auth
from app.domain.mandates import AgentIdentity, AgentIdentityOrigin, AgentIdentityStatus
from app.agents.identity import TRAJECTORY_VERSION
from app.persistence.database import get_session

router = APIRouter(prefix="/v1/agent-identities", tags=["agent-identities"])


class AgentIdentityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    origin: AgentIdentityOrigin


def _read(identity: AgentIdentity) -> dict:
    return {
        "agent_id": identity.agent_id,
        "name": identity.name,
        "origin": identity.origin,
        "created_at": identity.created_at,
        "status": identity.status,
        "policy_id": identity.policy_id,
        "trajectory_version": identity.trajectory_version,
    }


@router.post("", status_code=201)
def create_agent_identity(
    payload: AgentIdentityCreate,
    session: Session = Depends(get_session),
    m2m_context_id: str = Depends(require_m2m_auth),
) -> dict:
    if payload.origin != AgentIdentityOrigin.EXTERNAL_API_AGENT:
        raise HTTPException(status_code=422, detail="EXTERNAL_M2M_IDENTITY_ORIGIN_REQUIRED")
    if session.get(AgentIdentity, payload.agent_id) is not None:
        raise HTTPException(status_code=409, detail="AGENT_IDENTITY_EXISTS")
    identity = AgentIdentity(
        agent_id=payload.agent_id,
        name=payload.name,
        origin=payload.origin.value,
        status=AgentIdentityStatus.ACTIVE.value,
        trajectory_version=TRAJECTORY_VERSION,
        m2m_context_id=m2m_context_id,
    )
    session.add(identity)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="AGENT_IDENTITY_EXISTS") from error
    session.refresh(identity)
    return _read(identity)


@router.get("/{agent_id}")
def get_agent_identity(
    agent_id: str,
    session: Session = Depends(get_session),
    m2m_context_id: str = Depends(require_m2m_auth),
) -> dict:
    identity = session.get(AgentIdentity, agent_id)
    if (
        identity is None
        or identity.origin != AgentIdentityOrigin.EXTERNAL_API_AGENT.value
        or identity.status != AgentIdentityStatus.ACTIVE.value
        or not identity.m2m_context_id
        or not hmac.compare_digest(identity.m2m_context_id, m2m_context_id)
    ):
        raise HTTPException(status_code=404, detail="AGENT_IDENTITY_MISSING")
    return _read(identity)
