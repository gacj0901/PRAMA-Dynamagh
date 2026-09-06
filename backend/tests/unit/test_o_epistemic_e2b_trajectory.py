"""E2-B categorical trajectory contract tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain.mandates import CryptoPriceEvidence, Evidence
from app.epistemic.contracts import build_crypto_price_evidence, build_crypto_price_target, build_evidence_requirement, canonical_hash
from app.epistemic.evaluator import evaluate_crypto_price
from app.epistemic.trajectory import (
    E1RelationalSnapshot,
    E2BTrajectoryPoint,
    build_transition_stream,
    derive_transition,
    replay_transition_stream,
)


UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, tzinfo=UTC)
TARGET_ID = "22222222-2222-4222-8222-222222222222"
MANDATE_ID = "11111111-1111-4111-8111-111111111111"


def _snapshot(
    evaluation_id: str,
    *,
    requirement_state: str = "SATISFIED",
    relations: tuple[dict, ...] = (),
    structural_state: str = "COMPLETE",
) -> E1RelationalSnapshot:
    canonical_relations = tuple(sorted(relations, key=lambda item: item["relation_id"]))
    requirement_states = (
        {
            "requirement_id": "r2",
            "requirement_type": "quote_currency",
            "required": True,
            "state": requirement_state,
            "supporting_relation_ids": tuple(
                item["relation_id"] for item in canonical_relations if item["relation_state"] == "SATISFIES"
            ),
            "contradicting_relation_ids": tuple(
                item["relation_id"] for item in canonical_relations if item["relation_state"] == "CONTRADICTS"
            ),
            "unresolved_relation_ids": (),
            "not_applicable_relation_ids": (),
        },
    )
    return E1RelationalSnapshot(
        evaluation_id=evaluation_id,
        canonical_hash=canonical_hash(
            {
                "target_id": TARGET_ID,
                "requirement_states": requirement_states,
                "relations": canonical_relations,
                "structural_state": structural_state,
            }
        ),
        target_id=TARGET_ID,
        requirement_states=requirement_states,
        relations=canonical_relations,
        structural_state=structural_state,
        observer_version="O_EPISTEMIC-v0.1",
        contract_version="e1-c2-crypto-price-v0.1",
        algorithm_version="e1-c2-deterministic-relational-v0.1",
    )


def _relation(relation_id: str, evidence_id: str, state: str) -> dict:
    return {
        "relation_id": relation_id,
        "requirement_id": "r2",
        "evidence_id": evidence_id,
        "relation_state": state,
        "relation_basis": {"rule": "exact_field_match", "observed": evidence_id},
    }


def _e1_trajectory_points() -> tuple[E2BTrajectoryPoint, ...]:
    target = build_crypto_price_target(
        mandate_id=MANDATE_ID,
        target_id=TARGET_ID,
        asset="BTC",
        quote_currency="USD",
        as_of=T0,
    )
    requirement_types = (
        "asset_identity",
        "quote_currency",
        "price_value",
        "temporal_applicability",
    )
    requirements = [
        build_evidence_requirement(
            target_id=TARGET_ID,
            requirement_id=f"r-{requirement_type}",
            requirement_type=requirement_type,
            parameters={"max_age_seconds": 300} if requirement_type == "temporal_applicability" else {},
        )
        for requirement_type in requirement_types
    ]

    def evaluate(
        evaluation_id: str,
        *,
        price: Decimal | None = Decimal("50000"),
        quote: str = "USD",
        observed_at: datetime = T0,
    ) -> E2BTrajectoryPoint:
        evidence_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        evidence = Evidence(
            evidence_id=evidence_id,
            mandate_id=MANDATE_ID,
            evidence_type="TELEGRAPH_RESULT",
            source_kind="TELEGRAPH",
            source_intent="CRYPTO_PRICE",
            source_miner_id="miner-1",
            source_signal_hash="0xsignal-1",
            normalized_payload={"fixture": evaluation_id},
            content_hash=canonical_hash({"fixture": evaluation_id}),
            normalizer_version="telegraph-evidence-v0",
            provenance_status="VERIFIED",
            admissibility="ADMITTED",
            limitation_codes=[],
        )
        typed = CryptoPriceEvidence(
            crypto_price_evidence_id=f"typed-{evaluation_id}",
            evidence_id=evidence_id,
            asset="BTC",
            quote_currency=quote,
            price_value=price,
            observed_at=observed_at,
            schema_version="crypto-price-evidence-v0.1",
            canonical_hash=canonical_hash({"typed": evaluation_id}),
        )
        result = evaluate_crypto_price(
            target=target,
            requirements=requirements,
            evidence=[evidence],
            typed_evidence_by_id={evidence_id: typed},
        )
        snapshot = E1RelationalSnapshot.from_evaluation(
            result.evaluation,
            relations=result.relations,
            evaluation_id=evaluation_id,
        )
        return E2BTrajectoryPoint(event_index=int(evaluation_id[1:]), snapshot=snapshot)

    return (
        evaluate("g0", price=None),
        evaluate("g1"),
        evaluate("g2", quote="EUR"),
        evaluate("g3"),
        evaluate("g4", observed_at=T0 - timedelta(seconds=301)),
    )


def test_relation_and_evidence_deltas_preserve_contradiction_attribution():
    previous = _snapshot("eval-previous", relations=(_relation("rel-1", "e1", "SATISFIES"),))
    current = _snapshot(
        "eval-current",
        requirement_state="CONTRADICTED",
        structural_state="CONTRADICTED",
        relations=(
            _relation("rel-1", "e1", "SATISFIES"),
            _relation("rel-2", "e2", "CONTRADICTS"),
        ),
    )
    transition = derive_transition(
        previous,
        current,
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
        transition_id="incidental-a",
    )
    assert transition.previous_requirement_state == "SATISFIED"
    assert transition.current_requirement_state == "CONTRADICTED"
    assert transition.previous_evaluation_hash == previous.canonical_hash
    assert transition.current_evaluation_hash == current.canonical_hash
    assert transition.added_relation_ids == ("rel-2",)
    assert transition.added_contradicting_evidence_ids == ("e2",)
    assert transition.added_supporting_evidence_ids == ()
    assert transition.transition_basis["transition_kind"] == "STATE_CHANGE"
    assert transition.transition_basis["relation_state_changes"] == []


def test_same_state_relational_change_and_exact_noop_are_distinct():
    previous = _snapshot("eval-previous", relations=(_relation("rel-1", "e1", "SATISFIES"),))
    corroborated = _snapshot(
        "eval-corroborated",
        relations=(
            _relation("rel-1", "e1", "SATISFIES"),
            _relation("rel-2", "e2", "SATISFIES"),
        ),
    )
    same_state = derive_transition(
        previous,
        corroborated,
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
    )
    assert same_state.transition_basis["transition_kind"] == "SAME_STATE_RELATIONAL_CHANGE"
    assert same_state.added_supporting_evidence_ids == ("e2",)

    exact_noop = derive_transition(
        previous,
        _snapshot("different-evaluation-id", relations=(_relation("rel-1", "e1", "SATISFIES"),)),
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
        transition_id="different-incidental-id",
    )
    assert exact_noop.transition_basis["transition_kind"] == "EXACT_NO_OP"
    assert same_state.canonical_hash != exact_noop.canonical_hash
    same_semantics = derive_transition(
        previous,
        _snapshot("third-evaluation-id", relations=(_relation("rel-1", "e1", "SATISFIES"),)),
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
        transition_id="third-incidental-id",
    )
    assert exact_noop.canonical_hash == same_semantics.canonical_hash

    changed_previous_hash = derive_transition(
        E1RelationalSnapshot(
            **{**previous.__dict__, "canonical_hash": "0xprevious-changed"}
        ),
        corroborated,
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
    )
    changed_current_hash = derive_transition(
        previous,
        E1RelationalSnapshot(
            **{**corroborated.__dict__, "canonical_hash": "0xcurrent-changed"}
        ),
        previous_event_index=0,
        event_index=1,
        requirement_id="r2",
    )
    assert changed_previous_hash.canonical_hash != same_state.canonical_hash
    assert changed_current_hash.canonical_hash != same_state.canonical_hash


def test_relation_removal_and_state_change_are_set_based_and_order_invariant():
    previous = _snapshot(
        "eval-previous",
        relations=(
            _relation("rel-1", "e1", "SATISFIES"),
            _relation("rel-2", "e2", "CONTRADICTS"),
        ),
        requirement_state="CONTRADICTED",
        structural_state="CONTRADICTED",
    )
    current = _snapshot("eval-current", relations=(_relation("rel-1", "e1", "SATISFIES"),))
    transition = derive_transition(
        previous,
        current,
        previous_event_index=1,
        event_index=2,
        requirement_id="r2",
    )
    assert transition.removed_relation_ids == ("rel-2",)
    assert transition.removed_contradicting_evidence_ids == ("e2",)
    assert transition.previous_requirement_state == "CONTRADICTED"
    assert transition.current_requirement_state == "SATISFIED"

    reordered_previous = _snapshot(
        "other-previous",
        relations=(_relation("rel-2", "e2", "CONTRADICTS"), _relation("rel-1", "e1", "SATISFIES")),
        requirement_state="CONTRADICTED",
        structural_state="CONTRADICTED",
    )
    reordered_current = _snapshot(
        "other-current",
        relations=(_relation("rel-1", "e1", "SATISFIES"),),
    )
    reordered = derive_transition(
        reordered_previous,
        reordered_current,
        previous_event_index=1,
        event_index=2,
        requirement_id="r2",
        transition_id="another-incidental-id",
    )
    assert reordered.canonical_hash == transition.canonical_hash


def test_e1p_trajectory_reconstruction_and_replay_are_deterministic():
    points = _e1_trajectory_points()
    transitions = build_transition_stream(points)
    assert [(item.event_index, item.requirement_type, item.transition_basis["transition_kind"]) for item in transitions] == [
        (1, "price_value", "STATE_CHANGE"),
        (2, "quote_currency", "STATE_CHANGE"),
        (3, "quote_currency", "STATE_CHANGE"),
        (4, "temporal_applicability", "STATE_CHANGE"),
    ]
    assert [(item.previous_requirement_state, item.current_requirement_state) for item in transitions] == [
        ("UNRESOLVED", "SATISFIED"),
        ("SATISFIED", "CONTRADICTED"),
        ("CONTRADICTED", "SATISFIED"),
        ("SATISFIED", "UNRESOLVED"),
    ]
    replay = replay_transition_stream(points)
    assert [item.canonical_hash for item in replay] == [item.canonical_hash for item in transitions]
    assert [item.as_dict()["transition_basis"] for item in replay] == [item.transition_basis for item in transitions]
    assert build_transition_stream(points[:2])[0].canonical_hash == transitions[0].canonical_hash


def test_stream_requires_explicit_monotonic_event_index_and_excludes_exact_noops():
    points = _e1_trajectory_points()
    no_op_points = (points[0], points[0])
    try:
        build_transition_stream(no_op_points)
    except ValueError as error:
        assert "strictly increasing" in str(error)
    else:
        raise AssertionError("non-monotonic event index was accepted")

    exact = _snapshot("exact", relations=(_relation("rel-1", "e1", "SATISFIES"),))
    point_a = E2BTrajectoryPoint(0, _snapshot("a", relations=(_relation("rel-1", "e1", "SATISFIES"),)))
    point_b = E2BTrajectoryPoint(1, exact)
    assert build_transition_stream((point_a, point_b)) == ()
    included = build_transition_stream((point_a, point_b), include_exact_noops=True)
    assert len(included) == 1
    assert included[0].transition_basis["transition_kind"] == "EXACT_NO_OP"
