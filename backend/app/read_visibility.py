"""Server-side visibility checks for frontend-facing mandate read models."""

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

INTERNAL_ONLY = "INTERNAL_ONLY"


def is_internal_only(mandate) -> bool:
    """Treat either durable marker as internal; legacy rows remain visible."""
    visibility = str(getattr(mandate, "visibility", "PUBLIC") or "PUBLIC").upper()
    origin = str(getattr(mandate, "origin", "") or "").upper()
    return visibility == INTERNAL_ONLY or origin == "INTERNAL_VALIDATION"


def frontend_visibility_clause(column):
    """SQL clause preserving legacy NULL rows while excluding internal rows."""
    return or_(column.is_(None), column != INTERNAL_ONLY)


def require_frontend_mandate(session: Session, mandate_id: str):
    """Return an externally visible mandate or the same 404 for hidden rows."""
    from app.domain.mandates import Mandate

    mandate = session.get(Mandate, mandate_id)
    if mandate is None or is_internal_only(mandate):
        raise HTTPException(status_code=404, detail="MANDATE_MISSING")
    return mandate
