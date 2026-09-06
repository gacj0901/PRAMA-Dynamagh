"""Pure E1-C2 relational evaluator tests."""

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.mandates import Evidence, EvidenceRequirement
from app.epistemic.contracts import build_crypto_price_evidence, build_crypto_price_target
from app.epistemic.evaluator import (
    E1_C2_ALGORITHM_VERSION,
    E1_C2_CONTRACT_VERSION,
    E1_C2_OBSERVER_VERSION,
    TEMPORAL_WINDOW_UNRESOLVED,
    UNSPECIFIED_CONTRACT_CASE,
    build_e1_evidence_set_hash,
    build_evidence_relation,
    evaluate_crypto_price,
    replay_crypto_price,
)


UTC = timezone.utc
TARGET_ID = "11111111-1111-4111-8111-111111111111"
MANDATE_ID = "22222222-2222-4222-8222-222222222222"
AS_OF = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _target(*, asset="BTC", quote="USD", as_of=AS_OF):
    return build_crypto_price_target(
        mandate_id=MANDATE_ID,
        target_id=TARGET_ID,
        asset=asset,
        quote_currency=quote,
        as_of=as_of,
    )


def _requirement(requirement_type, *, required=True, parameters=None, suffix=None):
    suffix = suffix or requirement_type
    suffix_id = {
        "asset_identity": "000000000001",
        "quote_currency": "000000000002",
        "price_value": "000000000003",
        "temporal_applicability": "000000000004",
        "optional-price": "000000000005",
    }.get(suffix, "000000000099")
    return EvidenceRequirement(
        requirement_id=f"33333333-3333-4333-8333-{suffix_id}",
        target_id=TARGET_ID,
        requirement_type=requirement_type,
        parameters=parameters or {},
        required=required,
        contract_version="crypto-price-requirement-v0.1",
        canonical_hash=f"0x{suffix:0>64}"[:66],
    )


def _evidence(evidence_id, *, admissibility="ADMITTED", intent="CRYPTO_PRICE"):
    return Evidence(
        evidence_id=evidence_id,
        mandate_id=MANDATE_ID,
        evidence_type="TELEGRAPH_RESULT",
        source_kind="TELEGRAPH",
        source_intent=intent,
        source_miner_id="miner-1",
        source_signal_hash="0xsignal",
        normalized_payload={},
        content_hash=f"0x{evidence_id.replace('-', ''):0>64}"[:66],
        normalizer_version="telegraph-evidence-v0",
        provenance_status="VERIFIED",
        admissibility=admissibility,
        limitation_codes=[],
    )


def _typed(evidence_id, *, asset="BTC", quote="USD", price="50000", observed_at=AS_OF):
    return build_crypto_price_evidence(
        evidence_id=evidence_id,
        asset=asset,
        quote_currency=quote,
        price_value=Decimal(price),
        observed_at=observed_at,
        crypto_price_evidence_id=f"44444444-4444-4444-8444-{evidence_id[-12:]}",
    )


def _requirements(*, temporal_window=None, include_optional=False):
    requirements = [
        _requirement("asset_identity"),
        _requirement("quote_currency"),
        _requirement("price_value"),
        _requirement(
            "temporal_applicability",
            parameters={} if temporal_window is None else {"max_age_seconds": temporal_window},
        ),
    ]
    if include_optional:
        requirements.append(_requirement("price_value", required=False, suffix="optional-price"))
    return requirements


def _evaluate(requirements=None, evidence=None, typed=None, target=None):
    if evidence is None:
        evidence = [_evidence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")]
    if typed is None:
        typed = {item.evidence_id: _typed(item.evidence_id) for item in evidence if item.source_intent == "CRYPTO_PRICE"}
    return evaluate_crypto_price(
        target=target or _target(),
        requirements=requirements or _requirements(),
        evidence=evidence,
        typed_evidence_by_id=typed,
    )


def test_relation_hash_excludes_incidental_ids_and_timestamps():
    first = build_evidence_relation(
        target_id=TARGET_ID,
        requirement_id="r1",
        evidence_id="e1",
        relation_state="SATISFIES",
        relation_basis={"rule": "exact_field_match", "observed_value": "BTC"},
        relation_id="55555555-5555-4555-8555-555555555555",
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    second = build_evidence_relation(
        target_id="other-target",
        requirement_id="other-requirement",
        evidence_id="other-evidence",
        relation_state="SATISFIES",
        relation_basis={"rule": "exact_field_match", "observed_value": "BTC"},
        relation_id="66666666-6666-4666-8666-666666666666",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert first.canonical_hash == second.canonical_hash


def test_complete_and_exact_rules():
    result = _evaluate(requirements=_requirements(temporal_window=300))
    assert result.evaluation.structural_state == "COMPLETE"
    assert {item["state"] for item in result.evaluation.requirement_states} == {"SATISFIED"}
    assert all(item.relation_state == "SATISFIES" for item in result.relations)


def test_asset_and_quote_mismatches_contradict_without_aliases():
    target = _target(asset="ETH", quote="EUR")
    result = _evaluate(target=target, requirements=_requirements(temporal_window=300))
    states = {item["requirement_type"]: item["state"] for item in result.evaluation.requirement_states}
    assert states["asset_identity"] == "CONTRADICTED"
    assert states["quote_currency"] == "CONTRADICTED"
    assert states["price_value"] == "SATISFIED"
    assert result.evaluation.structural_state == "CONTRADICTED"


def test_missing_typed_datum_is_unresolved_and_fail_closed():
    requirements = _requirements()
    result = _evaluate(requirements=requirements, typed={})
    assert all(item["state"] == "UNRESOLVED" for item in result.evaluation.requirement_states)
    assert result.evaluation.structural_state == "INCOMPLETE"
    assert UNSPECIFIED_CONTRACT_CASE in result.evaluation.limitations


def test_temporal_window_is_explicit_or_unresolved():
    unresolved = _evaluate(requirements=_requirements())
    temporal = next(item for item in unresolved.evaluation.requirement_states if item["requirement_type"] == "temporal_applicability")
    assert temporal["state"] == "UNRESOLVED"
    assert TEMPORAL_WINDOW_UNRESOLVED in unresolved.evaluation.limitations

    resolved = _evaluate(requirements=_requirements(temporal_window=300))
    temporal = next(item for item in resolved.evaluation.requirement_states if item["requirement_type"] == "temporal_applicability")
    assert temporal["state"] == "SATISFIED"


def test_support_and_contradiction_are_both_preserved():
    first = _evidence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second = _evidence("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    result = _evaluate(
        requirements=[_requirement("quote_currency")],
        evidence=[first, second],
        typed={
            first.evidence_id: _typed(first.evidence_id, quote="USD"),
            second.evidence_id: _typed(second.evidence_id, quote="EUR"),
        },
    )
    relation_states = [item.relation_state for item in result.relations]
    assert relation_states == ["SATISFIES", "CONTRADICTS"]
    state = result.evaluation.requirement_states[0]
    assert state["state"] == "CONTRADICTED"
    assert len(state["supporting_relation_ids"]) == 1
    assert len(state["contradicting_relation_ids"]) == 1
    assert len(result.evaluation.contradictions) == 1


def test_not_applicable_does_not_satisfy_requirement():
    evidence = _evidence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", intent="STORM_ALERT")
    result = _evaluate(
        requirements=[_requirement("asset_identity")],
        evidence=[evidence],
        typed={evidence.evidence_id: _typed(evidence.evidence_id)},
    )
    assert result.relations[0].relation_state == "NOT_APPLICABLE"
    assert result.evaluation.requirement_states[0]["state"] == "UNRESOLVED"


def test_optional_unresolved_requirement_does_not_block_complete():
    result = _evaluate(
        requirements=[_requirement("price_value", required=False)],
        evidence=[],
        typed={},
    )
    assert result.evaluation.requirement_states[0]["state"] == "UNRESOLVED"
    assert result.evaluation.structural_state == "COMPLETE"


def test_rejected_evidence_is_not_consumed_and_set_hash_is_order_invariant():
    admitted = _evidence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    rejected = _evidence("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", admissibility="REJECTED")
    typed = {admitted.evidence_id: _typed(admitted.evidence_id)}
    result = _evaluate(
        requirements=[_requirement("price_value")],
        evidence=[rejected, admitted],
        typed=typed,
    )
    assert result.evaluation.source_evidence_ids == [admitted.evidence_id]
    assert rejected.evidence_id not in result.evaluation.evidence_set_hash
    forward = build_e1_evidence_set_hash([admitted, rejected], typed)
    reverse = build_e1_evidence_set_hash([rejected, admitted], typed)
    assert forward == reverse


def test_replay_and_ordering_are_exact():
    first = _evidence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second = _evidence("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    requirements = _requirements(temporal_window=300)
    typed = {first.evidence_id: _typed(first.evidence_id), second.evidence_id: _typed(second.evidence_id)}
    kwargs = {
        "target": _target(),
        "requirements": requirements,
        "typed_evidence_by_id": typed,
    }
    ordered = evaluate_crypto_price(evidence=[first, second], **kwargs)
    replayed = replay_crypto_price(evidence=[second, first], **kwargs)
    assert ordered.evaluation.canonical_hash == replayed.evaluation.canonical_hash
    assert ordered.evaluation.evidence_set_hash == replayed.evaluation.evidence_set_hash
    assert [item.relation_state for item in ordered.relations] == [item.relation_state for item in replayed.relations]
    assert [item.relation_basis for item in ordered.relations] == [item.relation_basis for item in replayed.relations]
    assert ordered.evaluation.algorithm_version == E1_C2_ALGORITHM_VERSION
    assert ordered.evaluation.contract_version == E1_C2_CONTRACT_VERSION
    assert ordered.evaluation.observer_version == E1_C2_OBSERVER_VERSION


def test_unsupported_requirement_fails_closed():
    result = _evaluate(requirements=[_requirement("future_requirement")])
    assert result.evaluation.requirement_states[0]["state"] == "UNRESOLVED"
    assert result.evaluation.structural_state == "INCOMPLETE"
    assert UNSPECIFIED_CONTRACT_CASE in result.evaluation.limitations
