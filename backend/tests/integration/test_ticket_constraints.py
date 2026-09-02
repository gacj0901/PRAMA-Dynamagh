import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.domain.mandates import Ticket

LIVE_TICKET = "ca4d6936-f0ed-47ee-a2ce-ca509a36c8aa"


@pytest.fixture
def session():
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = sessionmaker(bind=engine)
    value = factory()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


def clone(source: Ticket, *, decision_id: str, schema_version: str, ticket_hash: str) -> Ticket:
    return Ticket(ticket_id=str(uuid.uuid4()), mandate_id=source.mandate_id, decision_id=decision_id, schema_version=schema_version, canonical_payload=source.canonical_payload, ticket_hash=ticket_hash, hash_algorithm="keccak256", anchor_status="LOCAL_ONLY")


def constraint(error: IntegrityError) -> str | None:
    return getattr(getattr(error, "orig", None), "diag", None).constraint_name


def test_unique_decision_schema(session):
    original = session.get(Ticket, LIVE_TICKET)
    session.add(clone(original, decision_id=original.decision_id, schema_version=original.schema_version, ticket_hash="0x" + "a" * 64))
    with pytest.raises(IntegrityError) as raised:
        session.flush()
    assert constraint(raised.value) == "tickets_decision_id_schema_version_key"
    session.rollback()
    assert session.get(Ticket, LIVE_TICKET) is not None


def test_unique_ticket_hash(session):
    original = session.get(Ticket, LIVE_TICKET)
    session.add(clone(original, decision_id=str(uuid.uuid4()), schema_version="constraint-test", ticket_hash=original.ticket_hash))
    with pytest.raises(IntegrityError) as raised:
        session.flush()
    assert constraint(raised.value) == "tickets_ticket_hash_key"
    session.rollback()
    assert session.get(Ticket, LIVE_TICKET) is not None
