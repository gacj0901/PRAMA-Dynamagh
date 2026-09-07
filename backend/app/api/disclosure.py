"""Authenticated, contractually asserted presentation; never human observation."""
from datetime import datetime
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.m2m import require_m2m_auth
from app.domain.mandates import AgentIdentity, Mandate, UsageEvent
from app.persistence.database import get_session
from app.tickets.disclosure import append_event, iso
from app.tickets.public_identity import normalized_hash, ticket_by_hash, titular_check_contract

router = APIRouter(prefix="/v1/m2m/titular-check", tags=["agent-disclosure"])


class Presentation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_hash: str = Field(min_length=1, max_length=66)
    url: str = Field(min_length=1, max_length=256)
    presentation_context: str = Field(min_length=1, max_length=512)
    presented_at: datetime | None = None


def authenticated_identity(session, context_id):
    identities = session.query(AgentIdentity).filter_by(m2m_context_id=context_id, status="ACTIVE", origin="EXTERNAL_API_AGENT").all()
    # The legacy shared Bearer can own several identities. Do not pretend that
    # it distinguishes them. Presentation requires one unambiguous subject.
    if len(identities) != 1:
        raise HTTPException(409, "DISCLOSURE_AGENT_CONTEXT_AMBIGUOUS")
    return identities[0]


@router.post("/presented")
def presented(payload: Presentation, session: Session = Depends(get_session),
              context_id: str = Depends(require_m2m_auth)):
    identity = authenticated_identity(session, context_id)
    try:
        response_hash = normalized_hash(payload.response_hash)
        ticket = ticket_by_hash(session, response_hash)
    except ValueError:
        response_hash, ticket = None, None
    mandate = session.get(Mandate, ticket.mandate_id) if ticket else None
    owned = bool(mandate and mandate.origin == "M2M" and mandate.agent_identity_id == identity.agent_id and mandate.m2m_context_id and hmac.compare_digest(mandate.m2m_context_id, context_id))

    def reject(reason, code):
        append_event(session, "TITULAR_CHECK_PRESENTATION_INVALID", ticket=ticket if owned else None,
                     identity_id=identity.agent_id, response_hash=response_hash,
                     source="M2M_PRESENTATION_ACK", logical_key=f"{identity.agent_id}:{response_hash}:{reason}",
                     metadata={"reason": reason})
        session.commit()
        raise HTTPException(code, reason)

    if not owned:
        reject("RESPONSE_HASH_MISMATCH", 404)
    if payload.url != titular_check_contract(ticket)["url"]:
        reject("URL_MISMATCH", 422)
    delivery = session.query(UsageEvent).filter(
        UsageEvent.event_type == "TITULAR_CHECK_DELIVERED_TO_AGENT",
        UsageEvent.metadata_["response_hash"].as_string() == "0x" + response_hash,
        UsageEvent.metadata_["agent_identity_id"].as_string() == identity.agent_id,
    ).order_by(UsageEvent.created_at).first()
    if delivery is None:
        reject("DISCLOSURE_NOT_DELIVERED", 409)
    event = append_event(session, "TITULAR_CHECK_PRESENTED_BY_AGENT", ticket=ticket,
                         source="AGENT_CONTRACTUAL_ASSERTION", logical_key=f"{identity.agent_id}:{response_hash}",
                         metadata={"url": payload.url, "response_hash_preserved": True,
                                   "presentation_context_hash": hashlib.sha256(payload.presentation_context.encode()).hexdigest(),
                                   "reported_presented_at": iso(payload.presented_at) if payload.presented_at else None,
                                   "human_observation_proven": False})
    session.commit()
    return {"status": "PRESENTED_BY_AGENT", "event_id": event.event_id,
            "response_hash": ticket.ticket_hash, "human_observation_proven": False}
