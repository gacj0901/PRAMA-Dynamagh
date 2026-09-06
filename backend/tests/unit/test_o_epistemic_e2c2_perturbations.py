"""E2-C2 primitive relational perturbation characterization.

This is an offline fixture campaign.  It treats E2-B relation deltas as the
primitive response and deliberately does not define an omega or invoke PRAMA.
"""

from __future__ import annotations

from app.epistemic.contracts import canonical_hash
from app.epistemic.trajectory import (
    E1RelationalSnapshot,
    build_trajectory_lineage,
    derive_transition,
)


TARGET_ID = "22222222-2222-4222-8222-222222222222"
TARGET_CONTRACT_VERSION = "crypto-price-target-v0.1"
E1_OBSERVER_VERSION = "O_EPISTEMIC-v0.1"
E1_CONTRACT_VERSION = "e1-c2-crypto-price-v0.1"
E1_ALGORITHM_VERSION = "e1-c2-deterministic-relational-v0.1"
E1_CANONICALIZATION_VERSION = "e1-canonical-v0.1"


def _relation(
    relation_id: str,
    evidence_id: str,
    state: str,
    *,
    requirement_id: str = "r2",
    requirement_type: str = "quote_currency",
    basis: dict | None = None,
) -> dict:
    return {
        "relation_id": relation_id,
        "requirement_id": requirement_id,
        "evidence_id": evidence_id,
        "relation_state": state,
        "relation_basis": basis or {"rule": "exact_field_match", "observed": evidence_id},
        "requirement_type": requirement_type,
    }


def _requirement_state(relations: tuple[dict, ...]) -> str:
    states = {item["relation_state"] for item in relations}
    if "CONTRADICTS" in states:
        return "CONTRADICTED"
    if "SATISFIES" in states:
        return "SATISFIED"
    return "UNRESOLVED"


def _snapshot(
    evaluation_id: str,
    relations: tuple[dict, ...] = (),
    *,
    relation_order: tuple[dict, ...] | None = None,
    structural_state: str | None = None,
) -> E1RelationalSnapshot:
    canonical_relations = tuple(sorted(relations, key=lambda item: item["relation_id"]))
    requirement_id = "r2"
    requirement_type = "quote_currency"
    state = _requirement_state(canonical_relations)
    requirement_state = {
        "requirement_id": requirement_id,
        "requirement_type": requirement_type,
        "required": True,
        "state": state,
        "supporting_relation_ids": sorted(
            item["relation_id"]
            for item in canonical_relations
            if item["relation_state"] == "SATISFIES"
        ),
        "contradicting_relation_ids": sorted(
            item["relation_id"]
            for item in canonical_relations
            if item["relation_state"] == "CONTRADICTS"
        ),
        "unresolved_relation_ids": sorted(
            item["relation_id"]
            for item in canonical_relations
            if item["relation_state"] == "UNRESOLVED"
        ),
        "not_applicable_relation_ids": sorted(
            item["relation_id"]
            for item in canonical_relations
            if item["relation_state"] == "NOT_APPLICABLE"
        ),
    }
    body = {
        "target_id": TARGET_ID,
        "requirement_states": (requirement_state,),
        "relations": canonical_relations,
        "structural_state": structural_state or ("CONTRADICTED" if state == "CONTRADICTED" else "INCOMPLETE" if state == "UNRESOLVED" else "COMPLETE"),
    }
    return E1RelationalSnapshot(
        evaluation_id=evaluation_id,
        canonical_hash=canonical_hash(body),
        target_id=TARGET_ID,
        requirement_states=(requirement_state,),
        relations=relation_order if relation_order is not None else canonical_relations,
        structural_state=body["structural_state"],
        observer_version=E1_OBSERVER_VERSION,
        contract_version=E1_CONTRACT_VERSION,
        algorithm_version=E1_ALGORITHM_VERSION,
        target_contract_version=TARGET_CONTRACT_VERSION,
        canonicalization_version=E1_CANONICALIZATION_VERSION,
    )


def _multi_snapshot(evaluation_id: str, requirement_relations: dict[str, tuple[dict, ...]]) -> E1RelationalSnapshot:
    states = []
    all_relations: list[dict] = []
    for requirement_id, relations in sorted(requirement_relations.items()):
        canonical_relations = tuple(sorted(relations, key=lambda item: item["relation_id"]))
        state = _requirement_state(canonical_relations)
        states.append(
            {
                "requirement_id": requirement_id,
                "requirement_type": "quote_currency",
                "required": True,
                "state": state,
                "supporting_relation_ids": sorted(
                    item["relation_id"] for item in canonical_relations if item["relation_state"] == "SATISFIES"
                ),
                "contradicting_relation_ids": sorted(
                    item["relation_id"] for item in canonical_relations if item["relation_state"] == "CONTRADICTS"
                ),
                "unresolved_relation_ids": sorted(
                    item["relation_id"] for item in canonical_relations if item["relation_state"] == "UNRESOLVED"
                ),
                "not_applicable_relation_ids": sorted(
                    item["relation_id"] for item in canonical_relations if item["relation_state"] == "NOT_APPLICABLE"
                ),
            }
        )
        all_relations.extend(canonical_relations)
    structural_state = (
        "CONTRADICTED"
        if any(item["state"] == "CONTRADICTED" for item in states)
        else "INCOMPLETE"
        if any(item["state"] == "UNRESOLVED" for item in states)
        else "COMPLETE"
    )
    body = {
        "target_id": TARGET_ID,
        "requirement_states": tuple(states),
        "relations": tuple(sorted(all_relations, key=lambda item: item["relation_id"])),
        "structural_state": structural_state,
    }
    return E1RelationalSnapshot(
        evaluation_id=evaluation_id,
        canonical_hash=canonical_hash(body),
        target_id=TARGET_ID,
        requirement_states=tuple(states),
        relations=tuple(sorted(all_relations, key=lambda item: item["relation_id"])),
        structural_state=structural_state,
        observer_version=E1_OBSERVER_VERSION,
        contract_version=E1_CONTRACT_VERSION,
        algorithm_version=E1_ALGORITHM_VERSION,
        target_contract_version=TARGET_CONTRACT_VERSION,
        canonicalization_version=E1_CANONICALIZATION_VERSION,
    )


LINEAGE = build_trajectory_lineage(
    target_id=TARGET_ID,
    target_contract_version=TARGET_CONTRACT_VERSION,
    e1_observer_version=E1_OBSERVER_VERSION,
    e1_contract_version=E1_CONTRACT_VERSION,
    e1_algorithm_version=E1_ALGORITHM_VERSION,
    e1_canonicalization_version=E1_CANONICALIZATION_VERSION,
)


def _transition(previous: E1RelationalSnapshot, current: E1RelationalSnapshot, *, requirement_id: str = "r2"):
    return derive_transition(
        previous,
        current,
        previous_event_index=0,
        event_index=1,
        requirement_id=requirement_id,
        trajectory_lineage=LINEAGE,
    )


def _signature(transition) -> dict:
    return {
        "relations_added": transition.added_relation_ids,
        "relations_removed": transition.removed_relation_ids,
        "relation_state_changes": tuple(
            (
                item["relation_id"],
                item["previous"]["relation_state"],
                item["current"]["relation_state"],
            )
            for item in transition.transition_basis["relation_state_changes"]
        ),
        "support_added": transition.added_supporting_evidence_ids,
        "support_removed": transition.removed_supporting_evidence_ids,
        "contradiction_added": transition.added_contradicting_evidence_ids,
        "contradiction_removed": transition.removed_contradicting_evidence_ids,
        "requirement_state_transition": (
            transition.previous_requirement_state,
            transition.current_requirement_state,
        ),
        "target_state_transition": (
            transition.previous_structural_state,
            transition.current_structural_state,
        ),
    }


def test_p1_p2_p3_no_semantic_delta_and_order_invariance():
    support = _relation("rel-1", "e1", "SATISFIES")
    second_support = _relation("rel-2", "e2", "SATISFIES")
    previous = _snapshot("eval-previous", (support, second_support))
    exact_noop = _transition(previous, _snapshot("different-evaluation-id", (support, second_support)))
    metadata_only = _transition(previous, _snapshot("metadata-mutated", (support, second_support)))
    reordered = _transition(
        previous,
        _snapshot("reordered", (support, second_support), relation_order=(second_support, support)),
    )
    assert exact_noop.transition_basis["transition_kind"] == "EXACT_NO_OP"
    assert _signature(exact_noop)["relations_added"] == ()
    assert _signature(exact_noop)["relations_removed"] == ()
    assert exact_noop.canonical_hash == metadata_only.canonical_hash == reordered.canonical_hash


def test_p4_p5_p6_support_addition_and_loss_are_set_based():
    e1 = _relation("rel-1", "e1", "SATISFIES")
    e2 = _relation("rel-2", "e2", "SATISFIES")

    added = _transition(_snapshot("p4-before", (e1,)), _snapshot("p4-after", (e1, e2)))
    assert _signature(added)["support_added"] == ("e2",)
    assert added.current_requirement_state == "SATISFIED"

    non_sole_removed = _transition(_snapshot("p5-before", (e1, e2)), _snapshot("p5-after", (e1,)))
    assert _signature(non_sole_removed)["support_removed"] == ("e2",)
    assert non_sole_removed.current_requirement_state == "SATISFIED"

    sole_removed = _transition(_snapshot("p6-before", (e1,)), _snapshot("p6-after", ()))
    assert _signature(sole_removed)["support_removed"] == ("e1",)
    assert sole_removed.current_requirement_state == "UNRESOLVED"
    assert sole_removed.current_structural_state == "INCOMPLETE"


def test_p7_p8_p9_contradiction_and_replacement_preserve_attribution():
    support = _relation("rel-1", "e1", "SATISFIES")
    contradiction = _relation("rel-2", "e2", "CONTRADICTS")

    injected = _transition(_snapshot("p7-before", (support,)), _snapshot("p7-after", (support, contradiction)))
    assert _signature(injected)["support_added"] == ()
    assert _signature(injected)["contradiction_added"] == ("e2",)
    assert injected.current_requirement_state == "CONTRADICTED"

    removed = _transition(_snapshot("p8-before", (support, contradiction)), _snapshot("p8-after", (support,)))
    assert _signature(removed)["contradiction_removed"] == ("e2",)
    assert removed.current_requirement_state == "SATISFIED"

    replaced = _transition(_snapshot("p9-before", (support,)), _snapshot("p9-after", (contradiction,)))
    assert _signature(replaced)["support_removed"] == ("e1",)
    assert _signature(replaced)["contradiction_added"] == ("e2",)
    assert replaced.current_requirement_state == "CONTRADICTED"


def test_p10_valid_relation_basis_change_is_not_a_state_change():
    before = _relation("rel-price", "e1", "SATISFIES", basis={"rule": "typed_field_present", "observed_value": "50000"})
    after = _relation("rel-price", "e1", "SATISFIES", basis={"rule": "typed_field_present", "observed_value": "51000"})
    transition = _transition(_snapshot("p10-before", (before,)), _snapshot("p10-after", (after,)))
    assert transition.transition_basis["transition_kind"] == "SAME_STATE_RELATIONAL_CHANGE"
    assert transition.transition_basis["relation_state_changes"][0]["relation_id"] == "rel-price"
    assert transition.previous_requirement_state == transition.current_requirement_state == "SATISFIED"


def test_p13_p14_restoration_sequences_are_history_dependent_and_causal():
    support = _relation("rel-1", "e1", "SATISFIES")
    contradiction = _relation("rel-2", "e2", "CONTRADICTS")

    p13 = (
        _snapshot("p13-g0", (support,)),
        _snapshot("p13-g1", (support, contradiction)),
        _snapshot("p13-g2", (support,)),
    )
    p13_first = _transition(p13[0], p13[1])
    p13_second = _transition(p13[1], p13[2])
    assert (p13_first.previous_requirement_state, p13_first.current_requirement_state) == ("SATISFIED", "CONTRADICTED")
    assert (p13_second.previous_requirement_state, p13_second.current_requirement_state) == ("CONTRADICTED", "SATISFIED")
    assert _transition(p13[0], p13[1]).canonical_hash == p13_first.canonical_hash

    p14 = (
        _snapshot("p14-g0", (support,)),
        _snapshot("p14-g1", ()),
        _snapshot("p14-g2", (support,)),
    )
    p14_first = _transition(p14[0], p14[1])
    p14_second = _transition(p14[1], p14[2])
    assert (p14_first.previous_requirement_state, p14_first.current_requirement_state) == ("SATISFIED", "UNRESOLVED")
    assert (p14_second.previous_requirement_state, p14_second.current_requirement_state) == ("UNRESOLVED", "SATISFIED")


def test_projection_validation_uses_only_the_primitive_delta():
    support = _relation("rel-1", "e1", "SATISFIES")
    contradiction = _relation("rel-2", "e2", "CONTRADICTS")
    transition = _transition(_snapshot("before", (support,)), _snapshot("after", (support, contradiction)))
    signature = _signature(transition)

    assert signature["support_added"] == ()
    assert signature["support_removed"] == ()
    assert signature["contradiction_added"] == ("e2",)
    assert signature["contradiction_removed"] == ()
    assert signature["requirement_state_transition"] == ("SATISFIED", "CONTRADICTED")
    assert signature["target_state_transition"] == ("COMPLETE", "CONTRADICTED")


def test_information_loss_witnesses_preserve_distinct_primitive_surfaces():
    empty = _snapshot("empty", ())
    support_e1 = _snapshot("support-e1", (_relation("rel-e1", "e1", "SATISFIES"),))
    support_e2 = _snapshot("support-e2", (_relation("rel-e2", "e2", "SATISFIES"),))
    state_a = _transition(empty, support_e1)
    state_b = _transition(empty, support_e2)
    assert _signature(state_a)["requirement_state_transition"] == _signature(state_b)["requirement_state_transition"]
    assert _signature(state_a)["relations_added"] != _signature(state_b)["relations_added"]

    contradiction_e1 = _relation("rel-c1", "e1", "CONTRADICTS")
    contradiction_e2 = _relation("rel-c2", "e2", "CONTRADICTS")
    contradiction_a = _transition(_snapshot("c-a-before", ()), _snapshot("c-a-after", (contradiction_e1,)))
    contradiction_b = _transition(_snapshot("c-b-before", ()), _snapshot("c-b-after", (contradiction_e2,)))
    assert bool(_signature(contradiction_a)["contradiction_added"])
    assert bool(_signature(contradiction_b)["contradiction_added"])
    assert _signature(contradiction_a)["relations_added"] != _signature(contradiction_b)["relations_added"]

    target_a = _transition(
        _multi_snapshot("target-a-before", {"r1": (), "r2": ()}),
        _multi_snapshot("target-a-after", {"r1": (_relation("ra", "ea", "CONTRADICTS", requirement_id="r1"),), "r2": ()}),
        requirement_id="r1",
    )
    target_b = _transition(
        _multi_snapshot("target-b-before", {"r1": (), "r2": ()}),
        _multi_snapshot("target-b-after", {"r1": (), "r2": (_relation("rb", "eb", "CONTRADICTS", requirement_id="r2"),)}),
        requirement_id="r2",
    )
    assert target_a.current_structural_state == target_b.current_structural_state == "CONTRADICTED"
    assert target_a.requirement_id != target_b.requirement_id


def test_lineage_and_event_index_bound_causal_replay():
    support = _relation("rel-1", "e1", "SATISFIES")
    first = _snapshot("g0", ())
    second = _snapshot("g1", (support,))
    third = _snapshot("g2", (support, _relation("rel-2", "e2", "CONTRADICTS")))

    first_delta = _transition(first, second)
    with_future = _transition(first, second)
    assert first_delta.canonical_hash == with_future.canonical_hash
    assert third.canonical_hash != second.canonical_hash

    replayed = _transition(first, second)
    assert replayed.canonical_hash == first_delta.canonical_hash
