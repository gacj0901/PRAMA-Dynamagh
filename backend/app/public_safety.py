"""Fail-closed budget authorization for the public manual mandate path.

The API reserves the maximum public mandate budget before publishing work.
The worker subsequently verifies that durable reservation before it can call
Gateway.  PostgreSQL is the source of truth for money; Redis is used only for
the public request rate limit and the existing acquisition execution lock.
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
    return _decimal_setting("PUBLIC_DAILY_SPEND_CAP_USDC", "0.50")


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
    """Atomically reserve a public manual budget in PostgreSQL.

    The conditional upsert serializes concurrent reservations on the one
    ledger row for today.  ``spent + reserved`` can therefore never exceed
    the cap.  The caller must commit this together with the Mandate and task.
    """
    normalized = amount.quantize(_MICRO)
    if normalized <= 0 or normalized > public_max_mandate_usdc():
        raise HTTPException(status_code=422, detail="PUBLIC_MANDATE_BUDGET_EXCEEDED")
    cap = public_daily_spend_cap_usdc()
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
        )
    )


def verify_public_manual_reservation(session: Session, mandate_id: str, maximum: Decimal) -> PublicManualSpendReservation:
    """Return a locked valid reservation, or stop before Gateway is contacted."""
    try:
        reservation = (
            session.query(PublicManualSpendReservation)
            .filter_by(mandate_id=mandate_id)
            .with_for_update()
            .one_or_none()
        )
        if reservation is None or reservation.status != "RESERVED":
            raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
        if reservation.reserved_usdc <= 0 or reservation.reserved_usdc > maximum:
            raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
        return reservation
    except Exception as error:
        if isinstance(error, RuntimeError):
            raise
        raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE") from error


def settle_public_manual_spend(session: Session, mandate_id: str, actual_spend: Decimal) -> None:
    """Convert a reservation into immutable actual spend in the same commit as the call."""
    reservation = verify_public_manual_reservation(session, mandate_id, public_max_mandate_usdc())
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
    """Release only a definitely unspent reservation; uncertain failures keep it reserved."""
    reservation = (
        session.query(PublicManualSpendReservation)
        .filter_by(mandate_id=mandate_id)
        .with_for_update()
        .one_or_none()
    )
    if reservation is None or reservation.status != "RESERVED":
        return
    ledger = session.get(PublicManualSpendLedger, reservation.spend_date, with_for_update=True)
    if ledger is None or ledger.reserved_usdc < reservation.reserved_usdc:
        raise RuntimeError("PUBLIC_SPEND_AUTHORIZATION_INVALID")
    ledger.reserved_usdc -= reservation.reserved_usdc
    reservation.status = "RELEASED"
