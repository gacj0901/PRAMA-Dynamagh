"""Presentation identity derived exclusively from the existing canonical hash."""

import re

ISSUER_SUFFIX = "-prama-dynamagh"


def ticket_by_hash(session, response_hash):
    from sqlalchemy import func
    from app.domain.mandates import Ticket
    value = normalized_hash(response_hash)
    rows = session.query(Ticket).filter(func.lower(Ticket.ticket_hash).in_([value, "0x" + value])).all()
    return rows[0] if len(rows) == 1 else None


def normalized_hash(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value):
        raise ValueError("INVALID_RESPONSE_HASH")
    return value.removeprefix("0x").lower()


def hash_from_slug(slug: str) -> str:
    # Public paths have one canonical spelling: lowercase, no 0x prefix.
    if not re.fullmatch(r"[0-9a-f]{64}-prama-dynamagh", slug):
        raise ValueError("INVALID_RECEIPT")
    return slug.removesuffix(ISSUER_SUFFIX)


def titular_check_contract(ticket):
    if ticket is None:
        return {"status": "PENDING", "response_hash": None, "url": None}
    return {
        "status": "AVAILABLE",
        "response_hash": ticket.ticket_hash,
        "url": f"/titular-check/{normalized_hash(ticket.ticket_hash)}{ISSUER_SUFFIX}",
    }
