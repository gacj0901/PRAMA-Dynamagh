"""EpistemicTarget derivation from AcquisitionTask identity (Paso 2).

Identity is committed at enqueue; a Telegraph payload may only fill observed
state and must never rewrite the target.
"""

from types import SimpleNamespace

from app.epistemic.contracts import (
    TARGET_BUILDER_VERSION,
    build_target_from_acquisition,
    canonical_hash,
)


def _task(**overrides):
    base = dict(
        requested_intent="CRYPTO_PRICE",
        target_subject="BTC",
        target_property="spot_price",
        target_unit="USD",
        temporal_scope={"as_of": "2026-09-11T12:00:00Z"},
        target_constraints={"tolerance_bps": 25},
        target_schema_version="crypto-price-v0.1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_target_identity_is_deterministic():
    t1 = build_target_from_acquisition(_task(), mandate_id="m-1")
    t2 = build_target_from_acquisition(_task(), mandate_id="m-1")
    assert t1.canonical_hash == t2.canonical_hash
    assert t1.contract_version == TARGET_BUILDER_VERSION


def test_observed_value_can_never_redefine_identity():
    base = _task()
    target_before = build_target_from_acquisition(base, mandate_id="m-1")
    fake_evidence_hash = canonical_hash({"price": "99999"})
    # Even with a "known" observed hash, identity fields stay the same
    target_after = build_target_from_acquisition(base, mandate_id="m-1")
    assert target_before.canonical_hash == target_after.canonical_hash
    assert target_after.parameters["subject"] == "BTC"
    assert target_after.parameters["property"] == "spot_price"
    assert target_after.parameters["unit"] == "USD"


def test_incompatible_evidence_does_not_mutate_target():
    task = _task(target_subject="BTC", target_property="spot_price")
    evil_payload = {"asset": "ETH/USD", "malicious": True}
    target = build_target_from_acquisition(task, mandate_id="m-1")
    assert target.parameters["subject"] == "BTC"
    assert "ETH" not in str(target.parameters)


def test_replay_rebuilds_identical_target():
    task = _task()
    original = build_target_from_acquisition(task, mandate_id="m-1", target_id="t-1")
    replayed = build_target_from_acquisition(task, mandate_id="m-1", target_id="t-1")
    assert original.canonical_hash == replayed.canonical_hash
    assert original.parameters == replayed.parameters
    assert original.temporal_scope == replayed.temporal_scope


def test_target_lineage_metadata_is_verbatim():
    task = _task()
    target = build_target_from_acquisition(task, mandate_id="mid")
    assert target.target_type == "CRYPTO_PRICE"
    assert target.parameters["schema_version"] == "crypto-price-v0.1"
    assert target.temporal_scope == {"as_of": "2026-09-11T12:00:00Z"}
    assert target.parameters["constraints"] == {"tolerance_bps": 25}


def test_legacy_tasks_without_schema_version_excluded():
    legacy = _task(target_schema_version=None)
    assert build_target_from_acquisition(legacy, mandate_id="m-1") is None
