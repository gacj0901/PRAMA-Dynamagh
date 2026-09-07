"""Hash-addressed, read-only projection of the existing safe Ticket share."""

from decimal import Decimal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from pydantic import BaseModel, ConfigDict, Field

from app.api.public_surfaces import public_ticket_summary
from app.domain.mandates import Ticket
from app.persistence.database import get_session
from app.pramagraph.replay import replay
from app.tickets.public_identity import hash_from_slug, normalized_hash, ticket_by_hash
from app.tickets.service import verify
from app.tickets.disclosure import append_event, ensure_issued
from app.tickets import human_presence as human

router = APIRouter(prefix="/v1/titular-check", tags=["titular-check"])


def resolve_slug(session, slug):
    try:
        response_hash = hash_from_slug(slug)
    except ValueError:
        raise HTTPException(404, "INVALID_RECEIPT") from None
    ticket = ticket_by_hash(session, response_hash)
    if ticket is None:
        raise HTTPException(404, "RECEIPT_NOT_FOUND")
    return ticket


def safe_receipt(session, ticket, request):
    response_hash = normalized_hash(ticket.ticket_hash)
    # Enforces the existing publication boundary, including origin restrictions.
    safe = public_ticket_summary(session, ticket.ticket_id, request)
    verification = {"status": "UNAVAILABLE", "payload_hash_match": None,
                    "source_artifacts_match": None, "reconstructed_hash": None}
    replay_status = "UNAVAILABLE"
    try:
        checked = verify(session, ticket)
        verification = {key: checked[key] for key in verification}
        try:
            replay_status = "VALID" if replay(session, ticket.mandate_id)["matches"] else "INVALID"
        except ValueError:
            replay_status = "INVALID"
        if replay_status == "INVALID":
            verification["status"] = "INVALID"
        if normalized_hash(verification["reconstructed_hash"]) != response_hash:
            verification["status"] = "INVALID"
    except (ValueError, TypeError, KeyError, AttributeError, NoResultFound, MultipleResultsFound):
        verification["status"] = "UNAVAILABLE"
    # Never forward the old UUID-based verification/replay locators or payloads.
    acquisitions = [
        {key: item[key] for key in ("status", "requested_intent", "intent", "miner", "cost_usdc", "duration_ms")}
        for item in safe["acquisitions"]
    ]
    return {
        "schema": "prama.titular-check.v0", "issuer": "PRAMA-Dynamagh",
        "response_hash": ticket.ticket_hash,
        "workflow": {key: safe["workflow"][key] for key in ("mandate_type", "origin", "status")},
        "created_at": safe["ticket"]["created_at"],
        "acquisitions": acquisitions,
        "cost_usdc": f"{sum((Decimal(item['cost_usdc']) for item in acquisitions), Decimal(0)):.6f}",
        "evidence": sorted(safe["evidence"], key=lambda item: item["evidence_id"]),
        "evaluation": safe["evaluation"], "decision": safe["decision"],
        "limitations": safe["limitations"],
        "ticket": {key: safe["ticket"][key] for key in ("schema_version", "anchor_status")},
        "verification": verification, "replay": {"status": replay_status},
    }


@router.get("/config")
def turnstile_config():
    key, _, _, _ = human.configuration()
    return {"site_key": key}


class ChallengeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=2048)


@router.post("/{slug}/challenge")
def challenge(slug: str, payload: ChallengeInput, request: Request, session: Session = Depends(get_session)):
    try:
        response_hash = hash_from_slug(slug)
    except ValueError:
        raise HTTPException(404, "INVALID_RECEIPT") from None
    human.require_origin(request)
    facts = human.limit_access(session, request, response_hash)
    human.validate_challenge(payload.token, response_hash)
    ticket = resolve_slug(session, slug)
    # Apply the safe-share publication restriction before issuing any access grant.
    public_ticket_summary(session, ticket.ticket_id, request)
    token, claims = human.grant(response_hash, facts)
    ensure_issued(session, ticket)
    append_event(session, "HUMAN_PRESENCE_VERIFIED", ticket=ticket, source="TURNSTILE_SITEVERIFY",
                 logical_key=claims["session_id"], metadata={**facts, "session_id": claims["session_id"]})
    session.commit()
    return {"status": "HUMAN_PRESENCE_VERIFIED", "access_token": token, "expires_in": 900}


@router.get("/{slug}")
def get_titular_check(slug: str, request: Request, session: Session = Depends(get_session)):
    try:
        response_hash = hash_from_slug(slug)
    except ValueError:
        raise HTTPException(404, "INVALID_RECEIPT") from None
    human.limit_access(session, request, response_hash)
    claims = human.require_grant(request, response_hash)
    ticket = resolve_slug(session, slug)
    receipt = safe_receipt(session, ticket, request)
    request_id = str(uuid.uuid4())
    append_event(session, "TITULAR_CHECK_OPENED_BY_TITULAR", ticket=ticket, source="GATED_RECEIPT_ACCESS",
                 logical_key=claims["session_id"], request_id=request_id,
                 metadata={"session_id": claims["session_id"], "identity_assurance": "HUMAN_PRESENCE_ONLY"})
    v = receipt["verification"]
    if v["status"] == "VALID" and v["payload_hash_match"] is True and v["source_artifacts_match"] is True and normalized_hash(v["reconstructed_hash"]) == response_hash:
        append_event(session, "TITULAR_CHECK_VERIFIED_BY_TITULAR", ticket=ticket, source="GATED_RECEIPT_VERIFICATION",
                     request_id=request_id, metadata={"session_id": claims["session_id"]})
    session.commit()
    return receipt


@router.post("/{slug}/acknowledge")
def acknowledge(slug: str, request: Request, session: Session = Depends(get_session)):
    try:
        response_hash = hash_from_slug(slug)
    except ValueError:
        raise HTTPException(404, "INVALID_RECEIPT") from None
    human.require_origin(request)
    claims = human.require_grant(request, response_hash)
    human.limit_access(session, request, response_hash)
    ticket = resolve_slug(session, slug)
    public_ticket_summary(session, ticket.ticket_id, request)
    # An acknowledgement is allowed only after this session loaded the receipt.
    from app.domain.mandates import UsageEvent
    opened = session.query(UsageEvent).filter(
        UsageEvent.event_type == "TITULAR_CHECK_OPENED_BY_TITULAR",
        UsageEvent.metadata_["metadata"]["session_id"].as_string() == claims["session_id"],
        UsageEvent.metadata_["response_hash"].as_string() == "0x" + response_hash,
    ).first()
    if opened is None:
        raise HTTPException(409, "RECEIPT_NOT_OPENED")
    event = append_event(session, "TITULAR_CHECK_ACKNOWLEDGED_BY_TITULAR", ticket=ticket,
                         source="EXPLICIT_ACKNOWLEDGEMENT", logical_key=claims["session_id"],
                         metadata={"session_id": claims["session_id"], "action_approval": False})
    session.commit()
    return {"status": "ACKNOWLEDGED", "event_id": event.event_id, "action_approval": False}
