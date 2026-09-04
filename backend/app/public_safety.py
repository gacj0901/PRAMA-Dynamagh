"""Fail-closed budget authorization for all paid mandate paths.

The API or private scheduler reserves the workflow maximum before publishing
work.  The worker subsequently verifies that durable reservation before it can
call Gateway.  PostgreSQL is the source of truth for money; Redis is used only
for request limiting and the existing acquisition execution lock.
"""

from __future__ import annotations

import os
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import redis
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.mandates import PublicManualSpendLedger, PublicManualSpendReservation
from app.redis_config import redis_url

_MICRO = Decimal("0.000001")
M2M_MAX_WORKFLOW_USDC = Decimal("0.010000")
logger = logging.getLogger(__name__)


def _decimal_setting(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.environ.get(name, default))
    except (InvalidOperation, ValueError) as error:
        raise RuntimeError(f"{name}_INVALID") from error
    if value <= 0 or value.as_tuple().exponent < -6:
        raise RuntimeError(f"{name}_INVALID")
    return value.quantize(_MICRO)


def public_max_mandate_usdc() -> Decimal:
    return _decimal_setting("PUBLIC_MAX_MANDATE_USDC", "0.010000")


def public_daily_spend_cap_usdc() -> Decimal:
    return global_daily_spend_cap_usdc()


def global_daily_spend_cap_usdc() -> Decimal:
    """Return the one shared daily cap for manual, M2M, and autonomous spend."""
    fallback = os.environ.get("PUBLIC_DAILY_SPEND_CAP_USDC", "0.50")
    return _decimal_setting("GLOBAL_DAILY_SPEND_CAP_USDC", fallback)


def m2m_max_workflow_usdc() -> Decimal:
    """Return the hard M2M paid-workflow ceiling.

    This is intentionally not configurable above 0.01 USDC.  A deployment
    may lower the ceiling, but no API or environment typo can raise it.
    """
    try:
        configured = Decimal(os.environ.get("M2M_MAX_WORKFLOW_USDC", str(M2M_MAX_WORKFLOW_USDC)))
    except (InvalidOperation, ValueError) as error:
        raise RuntimeError("M2M_MAX_WORKFLOW_USDC_INVALID") from error
    if configured <= 0 or configured.as_tuple().exponent < -6:
        raise RuntimeError("M2M_MAX_WORKFLOW_USDC_INVALID")
    return min(configured.quantize(_MICRO), M2M_MAX_WORKFLOW_USDC)


def public_rate_limit() -> tuple[int, int]:
    try:
        limit = int(os.environ.get("PUBLIC_MANDATE_RATE_LIMIT", "3"))
        window = int(os.environ.get("PUBLIC_MANDATE_RATE_WINDOW_SECONDS", "3600"))
    except ValueError as error:
        raise RuntimeError("PUBLIC_MANDATE_RATE_LIMIT_INVALID") from error
    if limit < 1 or window < 1:
        raise RuntimeError("PUBLIC_MANDATE_RATE_LIMIT_INVALID")
    return limit, window


def enforce_public_budget(budget: Decimal) -> None:
    if budget > public_max_mandate_usdc():
        raise HTTPException(status_code=422, detail="PUBLIC_MANDATE_BUDGET_EXCEEDED")


def _rate_key(request: Request) -> str:
    # The public frontend is the sole API proxy in production.  Deliberately
    # key on its transport peer instead of a client-controlled forwarding
    # header: this is a conservative global demo gate, never spoofable input.
    client = request.client.host if request.client else "unknown"
    return f"prama:public:mandates:rate:{client}"


def enforce_public_rate_limit(request: Request) -> None:
    """Consume one public creation slot or fail closed when Redis is unavailable."""
    limit, window = public_rate_limit()
    try:
        client = redis.from_url(redis_url())
        key = _rate_key(request)
        count = int(client.incr(key))
        if count == 1:
            client.expire(key, window)
    except (KeyError, redis.RedisError, ValueError) as error:
        logger.warning("PUBLIC_RATE_LIMIT_UNAVAILABLE:%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="PUBLIC_RATE_LIMIT_UNAVAILABLE") from error
    if count > limit:
        raise HTTPException(status_code=429, detail="PUBLIC_RATE_LIMITED")


def reserve_public_manual_spend(session: Session, mandate_id: str, amount: Decimal) -> None:
    """Atomically reserve a manual budget in PostgreSQL.

    The conditional upsert serializes concurrent reservations on the one
    ledger row for today.  ``spent + reserved`` can therefore never exceed
    the cap.  The caller must commit this together with the Mandate and task.
    """
    _reserve_spend(session, mandate_id, amount, public_max_mandate_usdc(), "MANUAL")


def reserve_m2m_spend(session: Session, mandate_id: str, amount: Decimal) -> None:
    """Atomically reserve an M2M budget on the shared G12 daily ledger."""
    _reserve_spend(session, mandate_id, amount, m2m_max_workflow_usdc(), "M2M")


def reserve_autonomous_spend(session: Session, mandate_id: str, amount: Decimal) -> None:
    """Atomically reserve a bounded paid autonomous budget on the same ledger."""
    _reserve_spend(session, mandate_id, amount, M2M_MAX_WORKFLOW_USDC, "AUTONOMOUS")


def _reserve_spend(session: Session, mandate_id: str, amount: Decimal, maximum: Decimal, origin: str) -> None:
    normalized = amount.quantize(_MICRO)
    if normalized <= 0 or normalized > maximum:
        raise HTTPException(status_code=422, detail="PUBLIC_MANDATE_BUDGET_EXCEEDED")
    cap = global_daily_spend_cap_usdc()
    if normalized > cap:
        raise HTTPException(status_code=429, detail="PUBLIC_DAILY_SPEND_CAP_EXCEEDED")
    spend_date = datetime.now(timezone.utc).date()
    try:
        row = session.execute(
            text(
                """
                INSERT INTO public_manual_spend_ledgers
                  (spend_date, reserved_usdc, spent_usdc, created_at, updated_at)
                VALUES (:spend_date, :amount, 0, NOW(), NOW())
                ON CONFLICT (spend_date) DO UPDATE
                SET reserved_usdc = public_manual_spend_ledgers.reserved_usdc + :amount,
                    updated_at = NOW()
                WHERE public_manual_spend_ledgers.spent_usdc
                    + public_manual_spend_ledgers.reserved_usdc + :amount <= :cap
                RETURNING spend_date
                """
            ),
            {"spend_date": spend_date, "amount": normalized, "cap": cap},
        ).first()
    except Exception as error:
        raise HTTPException(status_code=503, detail="PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE") from error
    if row is None:
        raise HTTPException(status_code=429, detail="PUBLIC_DAILY_SPEND_CAP_EXCEEDED")
    session.add(
        PublicManualSpendReservation(
            mandate_id=mandate_id,
            spend_date=spend_date,
            reserved_usdc=normalized,
            status="RESERVED",
            origin=origin,
        )
    )


def verify_public_manual_reservation(session: Session, mandate_id: str, maximum: Decimal) -> PublicManualSpendReservation:
    """Return a locked manual reservation, or stop before Gateway is contacted."""
    return verify_spend_reservation(session, mandate_id, maximum, "MANUAL")


def verify_spend_reservation(session: Session, mandate_id: str, maximum: Decimal, origin: str) -> PublicManualSpendReservation:
    """Return a locked valid reservation, or stop before Gateway is contacted."""
    try:
        reservation = (
            session.query(PublicManualSpendReservation)
            .filter_by(mandate_id=mandate_id)
            .with_for_update()
            .one_or_none()
        )
        if reservation is None or reservation.status != "RESERVED" or reservation.origin != origin:
            raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
        if reservation.reserved_usdc <= 0 or reservation.reserved_usdc > maximum:
            raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
        return reservation
    except Exception as error:
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE") from error


def settle_public_manual_spend(session: Session, mandate_id: str, actual_spend: Decimal) -> None:
    """Settle a manual reservation in the same commit as the call."""
    settle_spend(session, mandate_id, actual_spend, public_max_mandate_usdc(), "MANUAL")


def settle_m2m_spend(session: Session, mandate_id: str, actual_spend: Decimal) -> None:
    """Settle an M2M reservation in the same commit as the Telegraph call."""
    settle_spend(session, mandate_id, actual_spend, m2m_max_workflow_usdc(), "M2M")


def settle_autonomous_spend(session: Session, mandate_id: str, actual_spend: Decimal) -> None:
    """Settle an autonomous reservation in the same commit as the call."""
    settle_spend(session, mandate_id, actual_spend, M2M_MAX_WORKFLOW_USDC, "AUTONOMOUS")


def settle_spend(session: Session, mandate_id: str, actual_spend: Decimal, maximum: Decimal, origin: str) -> None:
    """Convert a reservation into immutable actual spend atomically."""
    reservation = verify_spend_reservation(session, mandate_id, maximum, origin)
    actual = actual_spend.quantize(_MICRO)
    if actual < 0 or actual > reservation.reserved_usdc:
        raise RuntimeError("PUBLIC_SPEND_SETTLEMENT_INVALID")
    ledger = session.get(PublicManualSpendLedger, reservation.spend_date, with_for_update=True)
    if ledger is None or ledger.reserved_usdc < reservation.reserved_usdc:
        raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
    ledger.reserved_usdc -= reservation.reserved_usdc
    ledger.spent_usdc += actual
    reservation.actual_spend_usdc = actual
    reservation.status = "SETTLED"


def release_public_manual_reservation(session: Session, mandate_id: str) -> None:
    """Release only a definitely unspent manual reservation."""
    release_spend_reservation(session, mandate_id, "MANUAL")


def release_spend_reservation(session: Session, mandate_id: str, origin: str) -> None:
    """Release only a definitely unspent reservation; uncertain failures keep it reserved."""
    reservation = (
        session.query(PublicManualSpendReservation)
        .filter_by(mandate_id=mandate_id)
        .with_for_update()
        .one_or_none()
    )
    if reservation is None or reservation.status != "RESERVED" or reservation.origin != origin:
        return
    ledger = session.get(PublicManualSpendLedger, reservation.spend_date, with_for_update=True)
    if ledger is None or ledger.reserved_usdc < reservation.reserved_usdc:
        raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
    ledger.reserved_usdc -= reservation.reserved_usdc
    reservation.status = "RELEASED"
