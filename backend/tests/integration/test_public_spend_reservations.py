"""PostgreSQL-backed G12 authorization tests; all rows are cleaned up."""

import os
import uuid
from datetime import datetime as real_datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import public_safety
from app.domain.mandates import Mandate, PublicManualSpendLedger, PublicManualSpendReservation


class FrozenDatetime:
    @classmethod
    def now(cls, tz=None):
        return real_datetime(2099, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def sessions(monkeypatch):
    monkeypatch.setattr(public_safety, "datetime", FrozenDatetime)
    monkeypatch.setenv("PUBLIC_MAX_MANDATE_USDC", "0.010000")
    monkeypatch.setenv("PUBLIC_DAILY_SPEND_CAP_USDC", "0.010000")
    factory = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]), autoflush=False)
    first, second, cleanup = factory(), factory(), factory()
    ids: list[str] = []
    try:
        yield first, second, cleanup, ids
    finally:
        first.rollback(); second.rollback()
        for mandate_id in ids:
            cleanup.query(PublicManualSpendReservation).filter_by(mandate_id=mandate_id).delete()
            cleanup.query(Mandate).filter_by(mandate_id=mandate_id).delete()
        cleanup.query(PublicManualSpendLedger).filter_by(spend_date=FrozenDatetime.now().date()).delete()
        cleanup.commit()
        first.close(); second.close(); cleanup.close()


def mandate(session, ids) -> Mandate:
    value = Mandate(actor_id="g12-test", text="safety reservation fixture", mandate_type="GENERAL", constraints={}, max_budget_usdc=Decimal("0.010000"), status="RECEIVED", origin="MANUAL")
    session.add(value); session.flush(); ids.append(value.mandate_id)
    return value


def test_completed_plus_reserved_cap_is_durable_and_fail_closed(sessions):
    first, second, cleanup, ids = sessions
    one = mandate(first, ids)
    public_safety.reserve_public_manual_spend(first, one.mandate_id, Decimal("0.010000"))
    first.commit()
    ledger = cleanup.get(PublicManualSpendLedger, FrozenDatetime.now().date())
    assert ledger.reserved_usdc == Decimal("0.010000") and ledger.spent_usdc == Decimal("0.000000")

    two = mandate(second, ids)
    with pytest.raises(HTTPException) as capped:
        public_safety.reserve_public_manual_spend(second, two.mandate_id, Decimal("0.010000"))
    assert capped.value.status_code == 429
    second.rollback()

    public_safety.settle_public_manual_spend(first, one.mandate_id, Decimal("0.010000"))
    first.commit()
    cleanup.expire_all()
    ledger = cleanup.get(PublicManualSpendLedger, FrozenDatetime.now().date())
    reservation = cleanup.get(PublicManualSpendReservation, one.mandate_id)
    assert ledger.reserved_usdc == Decimal("0.000000") and ledger.spent_usdc == Decimal("0.010000")
    assert reservation.status == "SETTLED" and reservation.actual_spend_usdc == Decimal("0.010000")
