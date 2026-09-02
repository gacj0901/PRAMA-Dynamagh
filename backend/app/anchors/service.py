from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.mandates import AnchorAttempt, Ticket, UsageEvent
from app.tickets.service import verify

BASE_SEPOLIA_CHAIN_ID = 84532
PRAMA_TICKET_ANCHOR_ADDRESS = "0x3c1a6acfd3b7ff981c31797533169e5ee36dd6e9"


def request_anchor(session: Session, ticket_id: str) -> tuple[AnchorAttempt, str]:
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise ValueError("TICKET_MISSING")
    result = verify(session, ticket)
    if result["status"] != "VALID":
        raise ValueError("TICKET_INVALID")
    existing = session.query(AnchorAttempt).filter_by(ticket_id=ticket_id).one_or_none()
    if existing:
        # A receipt retry can turn a prior diagnostic failure into a confirmed
        # on-chain result. A confirmed attempt must not retain that stale code.
        if existing.status == "CONFIRMED" and existing.failure_code is not None:
            existing.failure_code = None
        return existing, "ALREADY_ANCHORED" if existing.status == "CONFIRMED" else "ALREADY_ANCHOR_PENDING"
    if ticket.anchor_status != "LOCAL_ONLY":
        raise ValueError("ANCHOR_STATUS_INVALID")
    attempt = AnchorAttempt(
        ticket_id=ticket.ticket_id,
        chain_id=BASE_SEPOLIA_CHAIN_ID,
        contract_address=PRAMA_TICKET_ANCHOR_ADDRESS,
        status="PENDING",
    )
    ticket.anchor_status = "ANCHOR_PENDING"
    session.add_all([
        attempt,
        UsageEvent(mandate_id=ticket.mandate_id, event_type="TICKET_ANCHOR_REQUESTED", metadata_={"ticket_id": ticket.ticket_id}),
    ])
    session.flush()
    return attempt, "ANCHOR_PENDING"
