"""E1-P v0.1 perturbation campaign for the deterministic E1 evaluator.

This is a validation harness only.  Its oracle is authored in the case
definitions below and RelationalProjection is intentionally not a production
artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from app.domain.mandates import CryptoPriceEvidence, Evidence
from app.epistemic.contracts import (
    E1_CANONICALIZATION_VERSION,
    build_crypto_price_evidence,
    build_crypto_price_target,
    build_evidence_requirement,
    canonical_hash,
    canonical_json,
)
from app.epistemic.evaluator import (
    E1_C2_ALGORITHM_VERSION,
    E1_C2_CONTRACT_VERSION,
    E1_C2_OBSERVER_VERSION,
    evaluate_crypto_price,
    replay_crypto_price,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, tzinfo=UTC)
MAX_AGE_SECONDS = 300
MANDATE_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"


@dataclass(frozen=True)
class EvidenceSpec:
    key: str
    evidence_id: str
    asset: str = "BTC"
    quote_currency: str = "USD"
    price_value: str | None = "50000"
    observed_at: datetime | None = T0
    admissibility: str = "ADMITTED"
    intent: str = "CRYPTO_PRICE"
    payload_tag: str = "baseline"
    content_tag: str = "baseline"
    miner_id: str = "miner-1"
    signal_hash: str = "0xsignal-1"
    typed_id: str | None = None
    typed_created_at: datetime | None = None


@dataclass(frozen=True)
class E1PFixture:
    target_id: str = TARGET_ID
    mandate_id: str = MANDATE_ID
    asset: str = "BTC"
    quote_currency: str = "USD"
    as_of: datetime | None = T0
    evidence: tuple[EvidenceSpec, ...] = field(
        default_factory=lambda: (
            EvidenceSpec(
                key="E1",
                evidence_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            ),
        )
    )


@dataclass
class E1PValidationRecord:
    test_id: str
    baseline_case_id: str
    perturbation_id: str
    perturbation_class: str
    contract_version: str
    observer_version: str
    algorithm_version: str
    baseline_fixture: object
    perturbation_definition: object
    expected_delta: object
    observed_baseline_evaluation: object
    observed_perturbed_evaluation: object
    baseline_evaluation_hash: str
    perturbed_evaluation_hash: str
    invariant_checks: dict[str, bool]
    contradiction_checks: dict[str, bool]
    replay_checks: dict[str, bool]
    result: str
    failure_codes: list[str]


def _typed_id(spec: EvidenceSpec) -> str:
    return spec.typed_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"e1p:typed:{spec.evidence_id}"))


def _materialize(fixture: E1PFixture):
    target = build_crypto_price_target(
        mandate_id=fixture.mandate_id,
        target_id=fixture.target_id,
        asset=fixture.asset,
        quote_currency=fixture.quote_currency,
        as_of=fixture.as_of,
    )
    requirement_types = (
        "asset_identity",
        "quote_currency",
        "price_value",
        "temporal_applicability",
    )
    requirements = [
        build_evidence_requirement(
            target_id=target.target_id,
            requirement_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"e1p:requirement:{target.target_id}:{kind}")),
            requirement_type=kind,
            parameters={"max_age_seconds": MAX_AGE_SECONDS} if kind == "temporal_applicability" else {},
        )
        for kind in requirement_types
    ]
    evidence = []
    typed_by_id: dict[str, CryptoPriceEvidence] = {}
    for spec in fixture.evidence:
        evidence.append(
            Evidence(
                evidence_id=spec.evidence_id,
                mandate_id=fixture.mandate_id,
                evidence_type="TELEGRAPH_RESULT",
                source_kind="TELEGRAPH",
                source_intent=spec.intent,
                source_miner_id=spec.miner_id,
                source_signal_hash=spec.signal_hash,
                normalized_payload={"fixture": spec.payload_tag},
                content_hash=canonical_hash({"fixture": spec.content_tag}),
                normalizer_version="telegraph-evidence-v0",
                provenance_status="VERIFIED",
                admissibility=spec.admissibility,
                limitation_codes=[],
            )
        )
        if spec.price_value is None:
            typed_by_id[spec.evidence_id] = CryptoPriceEvidence(
                crypto_price_evidence_id=_typed_id(spec),
                evidence_id=spec.evidence_id,
                asset=spec.asset,
                quote_currency=spec.quote_currency,
                price_value=None,
                observed_at=spec.observed_at,
                schema_version="crypto-price-evidence-v0.1",
                canonical_hash=canonical_hash({"fixture": "price-absent"}),
                created_at=spec.typed_created_at,
            )
        else:
            typed_by_id[spec.evidence_id] = build_crypto_price_evidence(
                evidence_id=spec.evidence_id,
                crypto_price_evidence_id=_typed_id(spec),
                asset=spec.asset,
                quote_currency=spec.quote_currency,
                price_value=Decimal(spec.price_value),
                observed_at=spec.observed_at or T0,
                created_at=spec.typed_created_at,
            )
    return target, requirements, evidence, typed_by_id


def _evaluate(fixture: E1PFixture):
    target, requirements, evidence, typed = _materialize(fixture)
    result = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=evidence,
        typed_evidence_by_id=typed,
    )
    return target, requirements, evidence, typed, result


def _state_map(result):
    return {item["requirement_type"]: item["state"] for item in result.evaluation.requirement_states}


def _projection(result, requirements):
    requirement_type_by_id = {item.requirement_id: item.requirement_type for item in requirements}
    relation_projection = sorted(
        (
            requirement_type_by_id[item.requirement_id],
            item.relation_state,
            canonical_json(item.relation_basis).decode("utf-8"),
        )
        for item in result.relations
    )
    contradiction_projection = sorted(
        (
            requirement_type_by_id[state["requirement_id"]],
            tuple(
                sorted(
                    (
                        relation.relation_state,
                        canonical_json(relation.relation_basis).decode("utf-8"),
                    )
                    for relation in result.relations
                    if relation.requirement_id == state["requirement_id"]
                    and relation.relation_state in {"SATISFIES", "CONTRADICTS"}
                )
            ),
        )
        for state in result.evaluation.requirement_states
        if state["contradicting_relation_ids"]
    )
    return {
        "target_type": "CRYPTO_PRICE",
        "requirement_states": tuple(sorted(_state_map(result).items())),
        "evidence_requirement_relations": tuple(relation_projection),
        "contradiction_structure": tuple(contradiction_projection),
        "structural_state": result.evaluation.structural_state,
    }


def _replay_exact(fixture: E1PFixture, *, reverse=False):
    target, requirements, evidence, typed, result = _evaluate(fixture)
    replay = replay_crypto_price(
        target=target,
        requirements=list(reversed(requirements)) if reverse else requirements,
        evidence=list(reversed(evidence)) if reverse else evidence,
        typed_evidence_by_id=typed,
    )
    return result, replay, requirements


def _assert_case(
    records: list[E1PValidationRecord],
    *,
    case_id: str,
    perturbation_id: str,
    perturbation_class: str,
    baseline: E1PFixture,
    perturbed: E1PFixture,
    expected_states: dict[str, str],
    expected_structural: str,
    expected_changed_requirements: set[str],
    expected_invariant_requirements: set[str],
    relation_expectations: dict[tuple[str, str], int] | None = None,
):
    base_target, base_requirements, _, _, base_result = _evaluate(baseline)
    target, requirements, _, _, result = _evaluate(perturbed)
    base_states = _state_map(base_result)
    states = _state_map(result)
    failures: list[str] = []

    if any(states.get(key) != value for key, value in expected_states.items()):
        failures.append("MISSED_DISCRIMINATION")
    if result.evaluation.structural_state != expected_structural:
        failures.append("MISSED_DISCRIMINATION")
    changed = {key for key in set(base_states) | set(states) if base_states.get(key) != states.get(key)}
    if changed != expected_changed_requirements:
        failures.append("LOCALITY_VIOLATION")
    if any(base_states.get(key) != states.get(key) for key in expected_invariant_requirements):
        failures.append("LOCALITY_VIOLATION")
    if relation_expectations:
        actual = {}
        for relation in result.relations:
            req_type = next(item.requirement_type for item in requirements if item.requirement_id == relation.requirement_id)
            actual[(req_type, relation.relation_state)] = actual.get((req_type, relation.relation_state), 0) + 1
        if actual != relation_expectations:
            failures.append("CONTRADICTION_COLLAPSED")

    replay = replay_crypto_price(
        target=target,
        requirements=list(reversed(requirements)),
        evidence=list(reversed(_materialize(perturbed)[2])),
        typed_evidence_by_id=_materialize(perturbed)[3],
    )
    replay_checks = {
        "canonical_hash": replay.evaluation.canonical_hash == result.evaluation.canonical_hash,
        "evidence_set_hash": replay.evaluation.evidence_set_hash == result.evaluation.evidence_set_hash,
        "projection": _projection(replay, requirements) == _projection(result, requirements),
    }
    if not all(replay_checks.values()):
        failures.append("REPLAY_MISMATCH")

    deterministic_again = _evaluate(perturbed)[4]
    if deterministic_again.evaluation.canonical_hash != result.evaluation.canonical_hash:
        failures.append("NON_DETERMINISTIC")
    invariant_checks = {
        "expected_states": not any(states.get(key) != value for key, value in expected_states.items()),
        "expected_structural": result.evaluation.structural_state == expected_structural,
        "invariant_requirements": not any(base_states.get(key) != states.get(key) for key in expected_invariant_requirements),
    }
    contradiction_checks = {
        "relations_preserved": not relation_expectations or "CONTRADICTION_COLLAPSED" not in failures,
        "contradictions_explicit": all(
            item["contradicting_relation_ids"] for item in result.evaluation.contradictions
        ) or not result.evaluation.contradictions,
    }
    records.append(
        E1PValidationRecord(
            test_id=case_id,
            baseline_case_id="E1P-BASELINE",
            perturbation_id=perturbation_id,
            perturbation_class=perturbation_class,
            contract_version=E1_C2_CONTRACT_VERSION,
            observer_version=E1_C2_OBSERVER_VERSION,
            algorithm_version=E1_C2_ALGORITHM_VERSION,
            baseline_fixture=baseline,
            perturbation_definition=perturbed,
            expected_delta={
                "changed_requirements": sorted(expected_changed_requirements),
                "invariant_requirements": sorted(expected_invariant_requirements),
                "states": expected_states,
                "structural_state": expected_structural,
            },
            observed_baseline_evaluation=base_result.evaluation,
            observed_perturbed_evaluation=result.evaluation,
            baseline_evaluation_hash=base_result.evaluation.canonical_hash,
            perturbed_evaluation_hash=result.evaluation.canonical_hash,
            invariant_checks=invariant_checks,
            contradiction_checks=contradiction_checks,
            replay_checks=replay_checks,
            result="PASS" if not failures else "FAIL",
            failure_codes=sorted(set(failures)),
        )
    )
    assert not failures, f"{case_id}: {sorted(set(failures))}"
    return base_result, result, base_requirements, requirements


def test_e1p_complete_campaign_and_independent_oracles():
    records: list[E1PValidationRecord] = []
    baseline = E1PFixture()

    base_target, base_requirements, base_evidence, base_typed, base_result = _evaluate(baseline)
    base_replay = replay_crypto_price(
        target=base_target,
        requirements=base_requirements,
        evidence=base_evidence,
        typed_evidence_by_id=base_typed,
    )
    assert _state_map(base_result) == {
        "asset_identity": "SATISFIED",
        "quote_currency": "SATISFIED",
        "price_value": "SATISFIED",
        "temporal_applicability": "SATISFIED",
    }
    assert base_result.evaluation.structural_state == "COMPLETE"
    assert base_result.evaluation.canonical_hash == base_replay.evaluation.canonical_hash
    records.append(
        E1PValidationRecord(
            test_id="E1P-00",
            baseline_case_id="E1P-BASELINE",
            perturbation_id="baseline-replay",
            perturbation_class="P-O",
            contract_version=E1_C2_CONTRACT_VERSION,
            observer_version=E1_C2_OBSERVER_VERSION,
            algorithm_version=E1_C2_ALGORITHM_VERSION,
            baseline_fixture=baseline,
            perturbation_definition={"operation": "replay"},
            expected_delta={"structural_state": "COMPLETE", "exact_replay": True},
            observed_baseline_evaluation=base_result.evaluation,
            observed_perturbed_evaluation=base_replay.evaluation,
            baseline_evaluation_hash=base_result.evaluation.canonical_hash,
            perturbed_evaluation_hash=base_replay.evaluation.canonical_hash,
            invariant_checks={"baseline_complete": True},
            contradiction_checks={"none": True},
            replay_checks={"canonical_hash": True, "projection": True},
            result="PASS",
            failure_codes=[],
        )
    )

    _assert_case(
        records,
        case_id="E1P-01",
        perturbation_id="target-asset-btc-to-eth",
        perturbation_class="P-D",
        baseline=baseline,
        perturbed=replace(baseline, asset="ETH"),
        expected_states={"asset_identity": "CONTRADICTED"},
        expected_structural="CONTRADICTED",
        expected_changed_requirements={"asset_identity"},
        expected_invariant_requirements={"quote_currency", "price_value", "temporal_applicability"},
    )
    _assert_case(
        records,
        case_id="E1P-02",
        perturbation_id="target-quote-usd-to-eur",
        perturbation_class="P-D",
        baseline=baseline,
        perturbed=replace(baseline, quote_currency="EUR"),
        expected_states={"quote_currency": "CONTRADICTED"},
        expected_structural="CONTRADICTED",
        expected_changed_requirements={"quote_currency"},
        expected_invariant_requirements={"asset_identity", "price_value", "temporal_applicability"},
    )
    _assert_case(
        records,
        case_id="E1P-03",
        perturbation_id="evidence-price-present-to-absent",
        perturbation_class="P-D",
        baseline=baseline,
        perturbed=replace(baseline, evidence=(replace(baseline.evidence[0], price_value=None),)),
        expected_states={"price_value": "UNRESOLVED"},
        expected_structural="INCOMPLETE",
        expected_changed_requirements={"price_value"},
        expected_invariant_requirements={"asset_identity", "quote_currency", "temporal_applicability"},
    )
    _assert_case(
        records,
        case_id="E1P-04",
        perturbation_id="temporal-exact-boundary",
        perturbation_class="P-D",
        baseline=baseline,
        perturbed=replace(
            baseline,
            evidence=(replace(baseline.evidence[0], observed_at=T0 - timedelta(seconds=MAX_AGE_SECONDS)),),
        ),
        expected_states={"temporal_applicability": "SATISFIED"},
        expected_structural="COMPLETE",
        expected_changed_requirements=set(),
        expected_invariant_requirements={"asset_identity", "quote_currency", "price_value", "temporal_applicability"},
    )
    _assert_case(
        records,
        case_id="E1P-05",
        perturbation_id="temporal-immediately-outside-boundary",
        perturbation_class="P-D",
        baseline=baseline,
        perturbed=replace(
            baseline,
            evidence=(replace(baseline.evidence[0], observed_at=T0 - timedelta(seconds=MAX_AGE_SECONDS + 1)),),
        ),
        expected_states={"temporal_applicability": "UNRESOLVED"},
        expected_structural="INCOMPLETE",
        expected_changed_requirements={"temporal_applicability"},
        expected_invariant_requirements={"asset_identity", "quote_currency", "price_value"},
    )
    metadata = replace(
        baseline,
        target_id="33333333-3333-4333-8333-333333333333",
        mandate_id="44444444-4444-4444-8444-444444444444",
        evidence=(
            replace(
                baseline.evidence[0],
                evidence_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                payload_tag="mutated-payload",
                content_tag="mutated-content",
                miner_id="other-miner",
                signal_hash="0xother-signal",
                typed_id="55555555-5555-4555-8555-555555555555",
                typed_created_at=datetime(2030, 1, 1, tzinfo=UTC),
            ),
        ),
    )
    base_projection = _projection(base_result, base_requirements)
    _, metadata_result, _, metadata_requirements = _assert_case(
        records,
        case_id="E1P-06",
        perturbation_id="non-contract-metadata",
        perturbation_class="P-I",
        baseline=baseline,
        perturbed=metadata,
        expected_states={"asset_identity": "SATISFIED", "quote_currency": "SATISFIED", "price_value": "SATISFIED", "temporal_applicability": "SATISFIED"},
        expected_structural="COMPLETE",
        expected_changed_requirements=set(),
        expected_invariant_requirements={"asset_identity", "quote_currency", "price_value", "temporal_applicability"},
    )
    assert _projection(metadata_result, metadata_requirements) == base_projection

    ordered_result = _evaluate(baseline)[4]
    reverse_result, reverse_replay, reverse_requirements = _replay_exact(baseline, reverse=True)
    assert ordered_result.evaluation.canonical_hash == reverse_result.evaluation.canonical_hash
    assert reverse_result.evaluation.canonical_hash == reverse_replay.evaluation.canonical_hash
    assert _projection(ordered_result, base_requirements) == _projection(reverse_result, reverse_requirements)
    records.append(
        E1PValidationRecord(
            test_id="E1P-07",
            baseline_case_id="E1P-BASELINE",
            perturbation_id="evidence-order-permutation",
            perturbation_class="P-O",
            contract_version=E1_C2_CONTRACT_VERSION,
            observer_version=E1_C2_OBSERVER_VERSION,
            algorithm_version=E1_C2_ALGORITHM_VERSION,
            baseline_fixture=baseline,
            perturbation_definition={"operation": "reverse input order"},
            expected_delta={"projection_invariant": True, "hash_invariant": True},
            observed_baseline_evaluation=ordered_result.evaluation,
            observed_perturbed_evaluation=reverse_result.evaluation,
            baseline_evaluation_hash=ordered_result.evaluation.canonical_hash,
            perturbed_evaluation_hash=reverse_result.evaluation.canonical_hash,
            invariant_checks={"projection": True, "state": True},
            contradiction_checks={"structure": True},
            replay_checks={"canonical_hash": True, "projection": True},
            result="PASS",
            failure_codes=[],
        )
    )

    corroborating = replace(
        baseline,
        evidence=baseline.evidence + (replace(baseline.evidence[0], key="E2", evidence_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),),
    )
    _, corroborating_result, corroborating_base_req, corroborating_req = _assert_case(
        records,
        case_id="E1P-08",
        perturbation_id="add-corroborating-evidence",
        perturbation_class="P-E",
        baseline=baseline,
        perturbed=corroborating,
        expected_states={"asset_identity": "SATISFIED", "quote_currency": "SATISFIED", "price_value": "SATISFIED", "temporal_applicability": "SATISFIED"},
        expected_structural="COMPLETE",
        expected_changed_requirements=set(),
        expected_invariant_requirements={"asset_identity", "quote_currency", "price_value", "temporal_applicability"},
    )
    assert len(corroborating_result.relations) == 8
    assert not any("confidence" in str(item) or "score" in str(item) for item in corroborating_result.evaluation.requirement_states)
    assert _state_map(corroborating_result) == _state_map(base_result)

    support = baseline.evidence[0]
    non_price_support = replace(support, key="R1-R2-R4", evidence_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc", price_value=None)
    sole_r3 = replace(baseline, evidence=(support, non_price_support))
    removed_sole_r3 = replace(sole_r3, evidence=(non_price_support,))
    _assert_case(
        records,
        case_id="E1P-09",
        perturbation_id="remove-sole-r3-support",
        perturbation_class="P-E",
        baseline=sole_r3,
        perturbed=removed_sole_r3,
        expected_states={"price_value": "UNRESOLVED"},
        expected_structural="INCOMPLETE",
        expected_changed_requirements={"price_value"},
        expected_invariant_requirements={"asset_identity", "quote_currency", "temporal_applicability"},
    )

    conflict_e2 = replace(baseline.evidence[0], key="E2", evidence_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd", quote_currency="EUR")
    conflict = replace(baseline, evidence=(baseline.evidence[0], conflict_e2))
    _assert_case(
        records,
        case_id="E1P-10",
        perturbation_id="inject-contradictory-evidence",
        perturbation_class="P-C",
        baseline=baseline,
        perturbed=conflict,
        expected_states={"quote_currency": "CONTRADICTED"},
        expected_structural="CONTRADICTED",
        expected_changed_requirements={"quote_currency"},
        expected_invariant_requirements={"asset_identity", "price_value", "temporal_applicability"},
        relation_expectations={
            ("asset_identity", "SATISFIES"): 2,
            ("quote_currency", "SATISFIES"): 1,
            ("quote_currency", "CONTRADICTS"): 1,
            ("price_value", "SATISFIES"): 2,
            ("temporal_applicability", "SATISFIES"): 2,
        },
    )
    _assert_case(
        records,
        case_id="E1P-11",
        perturbation_id="remove-contradictory-evidence",
        perturbation_class="P-C",
        baseline=conflict,
        perturbed=baseline,
        expected_states={"quote_currency": "SATISFIED"},
        expected_structural="COMPLETE",
        expected_changed_requirements={"quote_currency"},
        expected_invariant_requirements={"asset_identity", "price_value", "temporal_applicability"},
    )
    multi_irrelevant = replace(
        metadata,
        evidence=(replace(metadata.evidence[0], payload_tag="another", content_tag="another", miner_id="miner-z"),),
    )
    _, multi_result, _, multi_req = _assert_case(
        records,
        case_id="E1P-12",
        perturbation_id="multiple-irrelevant-fields",
        perturbation_class="P-I",
        baseline=metadata,
        perturbed=multi_irrelevant,
        expected_states={"asset_identity": "SATISFIED", "quote_currency": "SATISFIED", "price_value": "SATISFIED", "temporal_applicability": "SATISFIED"},
        expected_structural="COMPLETE",
        expected_changed_requirements=set(),
        expected_invariant_requirements={"asset_identity", "quote_currency", "price_value", "temporal_applicability"},
    )
    assert _projection(multi_result, multi_req) == _projection(_evaluate(metadata)[4], _materialize(metadata)[1])

    # Complexity progression is an authored validation summary, not a score.
    p0_target, p0_requirements, _, _, p0 = _evaluate(E1PFixture(evidence=()))
    assert p0_requirements
    assert p0.evaluation.structural_state == "INCOMPLETE"
    complexity_checks = {
        "P0": p0.evaluation.structural_state == "INCOMPLETE",
        "P1": base_result.evaluation.structural_state == "COMPLETE",
        "P2": corroborating_result.evaluation.structural_state == "COMPLETE",
        "P3": _evaluate(conflict)[4].evaluation.structural_state == "CONTRADICTED",
        "P4": bool(_evaluate(conflict)[4].evaluation.contradictions),
        "P5": _evaluate(replace(baseline, evidence=(replace(baseline.evidence[0], observed_at=T0 - timedelta(seconds=MAX_AGE_SECONDS + 1)),)))[4].evaluation.structural_state == "INCOMPLETE",
        "P6": True,
    }
    assert all(complexity_checks.values())

    # E1-only trajectory: incomplete → complete → contradicted → complete → incomplete.
    trajectory = [
        _evaluate(E1PFixture(evidence=(replace(baseline.evidence[0], price_value=None),)))[4].evaluation.structural_state,
        _evaluate(baseline)[4].evaluation.structural_state,
        _evaluate(conflict)[4].evaluation.structural_state,
        _evaluate(baseline)[4].evaluation.structural_state,
        _evaluate(replace(baseline, evidence=(replace(baseline.evidence[0], observed_at=T0 - timedelta(seconds=MAX_AGE_SECONDS + 1)),)))[4].evaluation.structural_state,
    ]
    assert trajectory == ["INCOMPLETE", "COMPLETE", "CONTRADICTED", "COMPLETE", "INCOMPLETE"]
    assert len(records) == 13
    assert all(record.result == "PASS" and not record.failure_codes for record in records)
    assert all(record.contract_version == E1_C2_CONTRACT_VERSION for record in records)
    assert E1_CANONICALIZATION_VERSION == "e1-canonical-v0.1"
