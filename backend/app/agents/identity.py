from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AgentIdentity,
    AgentIdentityOrigin,
    AgentIdentityStatus,
    AutonomyPolicy,
    Mandate,
)

TRAJECTORY_VERSION = "g13-agent-identity-v1"
INTERNAL_AUTONOMY_AGENT_ID = "autonomy-controller"


def get_or_create_m2m_identity(session: Session, agent_id: str, m2m_context_id: str) -> AgentIdentity:
    """Resolve the stable external identity used by an authenticated M2M caller."""

    identity = session.get(AgentIdentity, agent_id)
    if identity is not None:
        if identity.origin != AgentIdentityOrigin.EXTERNAL_API_AGENT.value:
            raise ValueError("M2M_AGENT_ID_ORIGIN_CONFLICT")
        if identity.status != AgentIdentityStatus.ACTIVE.value:
            raise ValueError("M2M_AGENT_INACTIVE")
        if identity.m2m_context_id != m2m_context_id:
            raise ValueError("M2M_AGENT_CONTEXT_CONFLICT")
        return identity

    identity = AgentIdentity(
        agent_id=agent_id,
        name=agent_id,
        origin=AgentIdentityOrigin.EXTERNAL_API_AGENT.value,
        status=AgentIdentityStatus.ACTIVE.value,
        trajectory_version=TRAJECTORY_VERSION,
        m2m_context_id=m2m_context_id,
    )
    session.add(identity)
    try:
        session.flush()
    except IntegrityError:
        # Another request may have established the same stable identity first.
        # The caller can safely continue only after resolving that committed row.
        session.rollback()
        identity = session.get(AgentIdentity, agent_id)
        if identity is None:
            raise
        if identity.origin != AgentIdentityOrigin.EXTERNAL_API_AGENT.value:
            raise ValueError("M2M_AGENT_ID_ORIGIN_CONFLICT")
        if identity.status != AgentIdentityStatus.ACTIVE.value:
            raise ValueError("M2M_AGENT_INACTIVE")
        if identity.m2m_context_id != m2m_context_id:
            raise ValueError("M2M_AGENT_CONTEXT_CONFLICT")
    return identity


def get_policy_identity(session: Session, policy: AutonomyPolicy) -> AgentIdentity | None:
    """Return the policy's explicit active subject; missing identity is fail-closed."""

    identity = session.query(AgentIdentity).filter_by(policy_id=policy.policy_id).one_or_none()
    if identity is None or identity.status != AgentIdentityStatus.ACTIVE.value:
        return None
    return identity


def policy_identity_required(session: Session, policy: AutonomyPolicy) -> AgentIdentity:
    identity = get_policy_identity(session, policy)
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    return identity


def mandate_attribution(mandate: Mandate) -> dict[str, str]:
    """Return stable attribution fields for persisted events and read models."""

    return {
        "origin": mandate.origin,
        "agent_id": mandate.agent_id or "",
        "agent_identity_id": mandate.agent_identity_id or "",
        "client_id": mandate.client_id or "",
    }
