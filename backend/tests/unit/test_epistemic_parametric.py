"""Structural invariants across all registry entries (not per-intent integration).

Every registered intent gets the same deterministic treatment: canonical hash
is stable, replay produces identical output, and schema is valid according to
its engine's declared fields.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.epistemic.contracts import canonical_hash, canonical_timestamp
from app.epistemic.registry import REGISTRY, lookup
from app.epistemic.registry import ENGINE_VALUE_FEED


def test_registry_completeness():
    for name, config in REGISTRY.items():
        assert config["engine"] in {"value_feed", "claim_verification"}
        assert "engine_version" in config
        if config["engine"] == "value_feed":
            assert "identity_fields" in config
            assert "value_field" in config


def test_registry_deterministic_canonical_hash():
    targets = [
        ("STOCK_PRICE", {"subject": "AAPL", "property": "spot_price", "unit": "USD"}),
        ("GAS_PRICE", {"subject": "ETH", "property": "gas_price", "unit": "gwei"}),
    ]
    for name, params in targets:
        if lookup(name) is None:
            continue
        hash1 = canonical_hash({"params": params, "schema": name})
        assert canonical_hash({"params": params, "schema": name}) == hash1


def test_value_feed_engine_requires_complete_identity():
    config = lookup("CRYPTO_PRICE")
    assert config is not None
    assert config["engine"] == ENGINE_VALUE_FEED
    assert "asset" in config["identity_fields"]
    assert "quote_currency" in config["identity_fields"]


def test_intents_are_deterministic_replayable_structures():
    for name, config in REGISTRY.items():
        assert isinstance(name, str) and name.isupper()
        assert isinstance(config, dict)
        assert "engine" in config or "identity_fields" in config


def test_value_feed_integration_end_to_end():
    from app.domain.mandates import AcquisitionTask, EpistemicTarget, Evidence, EvidenceRequirement, CryptoPriceEvidence
    from app.epistemic.contracts import build_target_from_acquisition
    from app.epistemic.evaluator import evaluate_crypto_price
    from datetime import datetime, timezone

    task = SimpleNamespace(
        acquisition_id="acq-1",
        mandate_id="m-1",
        status="SUCCEEDED",
        target_subject="BTC",
        target_property="spot_price",
        target_unit="USD",
        temporal_scope={"as_of": "2026-09-11T12:00:00Z"},
        target_constraints={"max_age_seconds": 60},
        target_schema_version="CRYPTO_PRICE",
        requested_intent="CRYPTO_PRICE",
    )
    target = build_target_from_acquisition(task, mandate_id="m-1")
    assert target is not None
    assert target.target_type == "CRYPTO_PRICE"

    evidence = Evidence(
        evidence_id="ev-1", mandate_id="m-1", acquisition_id="acq-1",
        evidence_type="TELEGRAPH_RESULT", source_kind="TELEGRAPH",
        source_intent="CRYPTO_PRICE", normalized_payload={"price": 77000},
        content_hash="x", normalizer_version="v", provenance_status="VERIFIED",
        admissibility="ADMITTED",
    )
    # The builder uses canonical target parameters {subject, property, unit, constraints}.
    # The evaluator compares against `asset`/`quote_currency` for v0.1 compatibility;
    # reuse the same values via typed evidence so the wiring stays faithful.
    typed = CryptoPriceEvidence(
        evidence_id="ev-1", asset=task.target_subject, quote_currency=task.target_unit,
        price_value=Decimal("77000"), observed_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),
        schema_version="crypto-price-evidence-v0.1",
    )
    requirements = [
        EvidenceRequirement(
            target_id=target.target_id, requirement_type="asset_identity",
            parameters={"target_type": "CRYPTO_PRICE"}, required=True,
            contract_version="crypto-price-evidence-v0.1",
        ),
        EvidenceRequirement(
            target_id=target.target_id, requirement_type="quote_currency",
            parameters={"target_type": "CRYPTO_PRICE"}, required=True,
            contract_version="crypto-price-evidence-v0.1",
        ),
        EvidenceRequirement(
            target_id=target.target_id, requirement_type="price_value",
            parameters={"target_type": "CRYPTO_PRICE"}, required=True,
            contract_version="crypto-price-evidence-v0.1",
        ),
        EvidenceRequirement(
            target_id=target.target_id, requirement_type="temporal_applicability",
            parameters={"max_age_seconds": 60}, required=True,
            contract_version="crypto-price-evidence-v0.1",
        ),
    ]
    for req in requirements:
        req.requirement_id = f"req-{req.requirement_type}"

    result = evaluate_crypto_price(
        target=target, requirements=requirements, evidence=[evidence],
        typed_evidence_by_id={"ev-1": typed}, mandate_id="m-1",
    )
    assert result.evaluation.structural_state == "COMPLETE"
    assert len(result.relations) == 4
    for r in result.relations:
        assert r.relation_state == "SATISFIES"
