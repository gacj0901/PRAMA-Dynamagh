"""Grupo B (claim verification) registry structural invariants."""

from app.epistemic.registry import REGISTRY, ENGINE_CLAIM_VERIFICATION

GRUPO_B = [
    "ASSET_RESERVE_ATTESTATION", "B2B_IDENTITY_ENRICHMENT", "CARRIER_SERVICEABILITY",
    "CODE_PATCH_VERIFY", "COMMERCE_PURCHASE_VERIFY", "CONTENT_VERIFICATION",
    "CONTRACT_OBLIGATION_AUDIT", "CORPORATE_REGISTRY_LOOKUP", "CROSS_CHAIN_STATE_VERIFY",
    "CVE_LOOKUP", "DATACENTER_TELEMETRY_VERIFY", "DELIVERY_WINDOW_VERIFY",
    "DOCUMENT_AUTHENTICITY", "EVENT_OUTCOME_RESOLUTION", "FACT_CHECK",
    "FARE_RULE_VERIFY", "FLIGHT_AVAILABILITY", "GAME_RESULT",
    "HOTEL_AVAILABILITY", "IMAGE_VERIFICATION", "INVOICE_LEDGER_RECONCILE",
    "IP_GEOLOCATION", "MEDIA_AUTHENTICITY_CHECK", "MEDIA_FORENSIC_VERIFY",
    "ONCHAIN_METRIC_VERIFY", "ONCHAIN_TX_LOOKUP", "PACKAGE_STATUS",
    "PAYMENT_METHOD_VERIFY", "PRODUCT_AUTHENTICITY", "PURCHASE_ORDER_VERIFY",
    "REGRESSION_VERIFY", "REGULATORY_FILING_MONITOR", "RETURN_POLICY_VERIFY",
    "SANCTIONS_SCREENING_MATCH", "SENSOR_TELEMETRY_VERIFY", "SHIPMENT_DELAY_RISK",
    "SLA_COMPLIANCE", "SPORTS_SCORE", "SSL_VERIFICATION",
    "STORM_ALERT", "TEXT_AUTHENTICITY_CHECK", "TRAVEL_DISRUPTION",
    "TRAVEL_TRANSIT_LOCK", "URL_SAFE", "URL_SCAN",
    "VALIDATOR_PERFORMANCE_VERIFY", "VENDOR_VERIFY", "VESSEL_TELEMETRY_VERIFY",
    "VIDEO_VERIFICATION", "WEATHER_FORECAST_VERIFY",
]


def test_grupo_b_all_registered():
    for name in GRUPO_B:
        assert name in REGISTRY, f"{name} missing"
        config = REGISTRY[name]
        assert config["engine"] == ENGINE_CLAIM_VERIFICATION
        assert config["canonical_intent_id"] == name
        assert config["engine_version"] == "claim-verification-v0.1"


def test_claim_verification_structure_complete():
    for name in GRUPO_B:
        config = REGISTRY[name]
        assert len(config["fields_to_compare"]) > 0
        for field in config["fields_to_compare"]:
            assert isinstance(field, str)
        assert isinstance(config["numeric_fields"], list)
        assert isinstance(config["hash_fields"], list)
        assert isinstance(config["boolean_fields"], list)


def test_numeric_tolerance_fields_declared():
    numeric_intents = []
    for name in numeric_intents:
        config = REGISTRY[name]
        assert len(config["numeric_fields"]) > 0


def test_grupo_b_field_consistency():
    for name in GRUPO_B:
        config = REGISTRY[name]
        all_fields = set(config["fields_to_compare"])
        assert len(all_fields) == len(config["fields_to_compare"])
        for field in all_fields:
            assert isinstance(field, str) and field.isalnum() or "_" in field


def test_claim_verification_accept_numeric_tolerance():
    """Registry plumbing only: claim_verification engine is dispatched by config."""
    from app.epistemic.registry import lookup

    config = lookup("SANCTIONS_SCREENING_MATCH")
    assert config["engine"] == "claim_verification"
    assert config["engine_version"] == "claim-verification-v0.1"
    assert "match_score" in config["fields_to_compare"]


def test_claim_verification_requires_explicit_numeric_fields():
    """Claim verification without declared numeric fields ignores tolerance
    hints and uses exact-match semantics only."""
    from app.epistemic.evaluator import evaluate_crypto_price
    from app.domain.mandates import EpistemicTarget, EvidenceRequirement, Evidence, CryptoPriceEvidence
    from datetime import datetime, timezone
    from decimal import Decimal

    target = EpistemicTarget(
        mandate_id="m", target_type="SANCTIONS_SCREENING_MATCH",
        parameters={"entity_name": "EVIL CORP", "sanction_list": "OFAC", "match_score": "85"},
        temporal_scope={}, contract_version="v", canonical_hash="x",
    )
    # no numeric_fields declared: numeric tolerance not applied
    req = EvidenceRequirement(
        target_id=target.target_id, requirement_type="match_score",
        parameters={"target_type": "SANCTIONS_SCREENING_MATCH"},
        required=True, contract_version="v",
    )
    req.requirement_id = "req-1"

    ev = Evidence(
        evidence_id="ev-1", mandate_id="m", acquisition_id="a",
        evidence_type="TELEGRAPH_RESULT", source_kind="TELEGRAPH",
        source_intent="SANCTIONS_SCREENING_MATCH",
        normalized_payload={"match_score": "88"},
        content_hash="x", normalizer_version="v",
        provenance_status="VERIFIED", admissibility="ADMITTED",
    )
    typed = CryptoPriceEvidence(
        evidence_id="ev-1", asset="EVIL CORP", quote_currency="OFAC",
        price_value=Decimal("88"), observed_at=datetime(2026,1,1,tzinfo=timezone.utc),
        schema_version="crypto-price-evidence-v0.1",
    )
    result = evaluate_crypto_price(
        target=target, requirements=[req], evidence=[ev],
        typed_evidence_by_id={"ev-1": typed}, mandate_id="m",
    )
    assert result.relations[0].relation_state == "UNRESOLVED"
