"""Pure E1-C1 canonicalization and typed-construction tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.epistemic.contracts import (
    E1_REQUIREMENT_CONTRACT_VERSION,
    build_crypto_price_evidence,
    build_crypto_price_target,
    build_evidence_requirement,
    canonical_decimal,
    canonical_timestamp,
)


UTC = timezone.utc


def test_target_hash_excludes_incidental_ids_and_created_at():
    first = build_crypto_price_target(
        mandate_id="mandate-a",
        target_id="target-a",
        asset="BTC",
        quote_currency="USD",
        as_of=datetime(2026, 9, 6, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
    )
    second = build_crypto_price_target(
        mandate_id="mandate-b",
        target_id="target-b",
        asset="BTC",
        quote_currency="USD",
        as_of=datetime(2026, 9, 6, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 6, 12, 2, tzinfo=UTC),
    )
    assert first.canonical_hash == second.canonical_hash
    assert first.parameters == {"asset": "BTC", "quote_currency": "USD", "as_of": "2026-09-06T12:00:00.000000Z"}
    assert first.temporal_scope == {"as_of": "2026-09-06T12:00:00.000000Z"}


def test_requirement_hash_is_deterministic_and_versioned():
    first = build_evidence_requirement(
        target_id="target-a",
        requirement_id="requirement-a",
        requirement_type="price_value",
        contract_version=E1_REQUIREMENT_CONTRACT_VERSION,
    )
    second = build_evidence_requirement(
        target_id="target-b",
        requirement_id="requirement-b",
        requirement_type="price_value",
        contract_version=E1_REQUIREMENT_CONTRACT_VERSION,
    )
    assert first.canonical_hash == second.canonical_hash
    assert first.contract_version == E1_REQUIREMENT_CONTRACT_VERSION


def test_typed_evidence_hash_is_stable_for_decimal_and_timestamp_forms():
    first = build_crypto_price_evidence(
        evidence_id="evidence-a",
        crypto_price_evidence_id="typed-a",
        asset="BTC",
        quote_currency="USD",
        price_value=Decimal("50000.0000"),
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
    )
    second = build_crypto_price_evidence(
        evidence_id="evidence-b",
        crypto_price_evidence_id="typed-b",
        asset="BTC",
        quote_currency="USD",
        price_value="50000",
        observed_at=datetime(2026, 9, 6, 14, tzinfo=timezone(timedelta(hours=2))),
        created_at=datetime(2026, 9, 6, 12, 2, tzinfo=UTC),
    )
    assert first.canonical_hash == second.canonical_hash
    assert first.price_value == second.price_value == Decimal("50000")
    assert first.observed_at == second.observed_at


def test_canonicalization_rejects_float_dependent_values_and_naive_time():
    with pytest.raises(TypeError):
        canonical_decimal(1.25)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        canonical_timestamp(datetime(2026, 9, 6, 12))
    with pytest.raises(TypeError):
        build_crypto_price_evidence(
            evidence_id="evidence-a",
            asset="BTC",
            quote_currency="USD",
            price_value=1.25,  # type: ignore[arg-type]
            observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        )


def test_only_frozen_crypto_price_requirement_types_are_constructible():
    with pytest.raises(ValueError):
        build_evidence_requirement(target_id="target-a", requirement_type="confidence")
