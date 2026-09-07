"""Append-only disclosure facts. No epistemic or operational authority."""
from datetime import datetime, timezone
import os
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.domain.mandates import Mandate, UsageEvent
from app.pramagraph.evaluation import digest
from app.tickets.public_identity import normalized_hash, titular_check_contract

VERSION = "titular-disclosure-v0"
PREFIX = "TITULAR_CHECK_"


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def deadline_seconds():
    value = int(os.environ.get("TITULAR_CHECK_PRESENTATION_DEADLINE_SECONDS", "30"))
    if not 1 <= value <= 86400:
        raise ValueError("INVALID_PRESENTATION_DEADLINE")
    return value


def append_event(session, event_type, *, ticket=None, identity_id=None, response_hash=None,
                 source, logical_key=None, request_id=None, metadata=None, at=None):
    """Unique PK + INSERT DO NOTHING make retries/concurrent writers idempotent."""
    mandate = session.get(Mandate, ticket.mandate_id) if ticket else None
    if ticket:
        response_hash = ticket.ticket_hash
        identity_id = mandate.agent_identity_id
    response_hash = "0x" + normalized_hash(response_hash) if response_hash else None
    event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{VERSION}:{event_type}:{logical_key}")) if logical_key else str(uuid.uuid4())
    occurred = at or utcnow()
    core = {
        "append_only": True, "schema_version": VERSION, "event_id": event_id, "event_type": event_type,
        "response_hash": response_hash, "ticket_id": ticket.ticket_id if ticket else None,
        "agent_identity_id": identity_id, "mandate_id": mandate.mandate_id if mandate else None,
        "run_id": mandate.autonomy_run_id if mandate else None,
        "occurred_at": iso(occurred), "source": source,
        "request_id": request_id or str(uuid.uuid4()), "metadata": metadata or {},
    }
    values = dict(event_id=event_id, event_type=event_type, mandate_id=core["mandate_id"],
                  created_at=occurred, metadata_={**core, "event_hash": digest(core)})
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    session.execute(insert(UsageEvent).values(**values).on_conflict_do_nothing(index_elements=["event_id"]))
    return session.get(UsageEvent, event_id)


def ensure_issued(session, ticket):
    contract = titular_check_contract(ticket)
    return append_event(session, PREFIX + "ISSUED", ticket=ticket, source="PRAMA_TICKET",
                        logical_key=normalized_hash(ticket.ticket_hash),
                        metadata={"url": contract["url"], "issuance_observed_at": iso(utcnow())})


def delivered(session, ticket, context_id, request_id=None):
    ensure_issued(session, ticket)
    return append_event(session, PREFIX + "DELIVERED_TO_AGENT", ticket=ticket,
                        source="M2M_RESPONSE_SENT", request_id=request_id,
                        logical_key=normalized_hash(ticket.ticket_hash) + ":" + context_id,
                        metadata={"url": titular_check_contract(ticket)["url"],
                                  "deadline_seconds": deadline_seconds(),
                                  "delivery_scope": "SERVER_TRANSPORT_ACCEPTED"})


def events_for_agent(session, identity_id):
    return session.query(UsageEvent).filter(
        UsageEvent.metadata_["schema_version"].as_string() == VERSION,
        UsageEvent.metadata_["agent_identity_id"].as_string() == identity_id,
    ).order_by(UsageEvent.created_at, UsageEvent.event_id).all()


def checked_core(event):
    data = dict(event.metadata_)
    expected = data.pop("event_hash")
    if digest(data) != expected or data["event_id"] != event.event_id or data["event_type"] != event.event_type or data["mandate_id"] != event.mandate_id or data["occurred_at"] != iso(event.created_at):
        raise ValueError("DISCLOSURE_EVENT_HASH_MISMATCH")
    return data
