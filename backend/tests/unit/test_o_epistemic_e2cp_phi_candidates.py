"""E2-C-P pre-kernel candidate validation."""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.epistemic.phi_candidates import (
    RelationSetPoint,
    canonical_relation_set,
    change_occurrence,
    relational_gain,
    relational_loss,
    relational_restoration,
    relational_set_distance,
    typed_relational_delta,
)


TARGET = "target-1"
LINEAGE = "lineage-1"
VERSIONS = (("e1", "v1"), ("e2", "v1"))


def _relation(
    relation_id: str,
    evidence_id: str,
    state: str = "SATISFIES",
    *,
    requirement_id: str = "r2",
    requirement_type: str = "quote_currency",
    basis: dict | None = None,
    created_at: str | None = None,
) -> dict:
    value = {
        "relation_id": relation_id,
        "evidence_id": evidence_id,
        "relation_state": state,
        "requirement_id": requirement_id,
        "requirement_type": requirement_type,
        "relation_basis": basis or {"rule": "exact_field_match", "observed": evidence_id},
    }
    if created_at is not None:
        value["created_at"] = created_at
    return value


def _set(*relations: dict, requirement_id: str = "r2", requirement_type: str = "quote_currency"):
    return canonical_relation_set(
        relations,
        target_id=TARGET,
        requirement_id=requirement_id,
        requirement_type=requirement_type,
    )


S1 = _relation("rel-1", "e1", "SATISFIES")
S2 = _relation("rel-2", "e2", "SATISFIES")
C2 = _relation("rel-2", "e2", "CONTRADICTS")
N1 = _relation("rel-1", "e1", "NOT_APPLICABLE")


def _point(index: int, relations, *, lineage: str = LINEAGE, versions=VERSIONS) -> RelationSetPoint:
    return RelationSetPoint(lineage, index, versions, frozenset(relations))


def test_semantic_relation_identity_excludes_incidental_ids_and_metadata():
    first = _set(_relation("uuid-a", "e1", created_at="2026-01-01T00:00:00Z"))
    second = _set(_relation("uuid-b", "e1", created_at="2030-01-01T00:00:00Z"))
    assert first == second
    assert relational_set_distance(first, second) == 0

    distinct_artifact = _set(_relation("uuid-c", "e2"))
    assert distinct_artifact != first
    assert relational_set_distance(first, distinct_artifact) == Fraction(1, 1)


def test_state_and_basis_changes_are_atomic_semantic_turnover():
    support = _set(S1)
    contradiction = _set(C2)
    basis_changed = _set(
        _relation("different-uuid", "e1", basis={"rule": "typed_field_present", "observed_value": "51000"})
    )
    assert relational_set_distance(support, contradiction) == 1
    assert relational_set_distance(support, basis_changed) == 1
    assert relational_loss(support, contradiction) == tuple(sorted(support))
    assert relational_gain(support, contradiction) == tuple(sorted(contradiction))


def test_distance_axioms_and_empty_cases():
    empty = _set()
    one = _set(S1)
    disjoint = _set(S2)
    two = _set(S1, S2)

    assert relational_set_distance(one, one) == 0
    assert relational_set_distance(one, two) == relational_set_distance(two, one) == Fraction(1, 2)
    assert relational_set_distance(empty, empty) == 0
    assert relational_set_distance(empty, one) == relational_set_distance(one, empty) == 1
    assert relational_set_distance(one, disjoint) == 1
    assert 0 <= relational_set_distance(one, two) <= 1


def test_distance_is_order_and_metadata_invariant_and_local():
    ordered = _set(S1, S2)
    reversed_input = _set(S2, S1)
    metadata = _set(
        _relation("runtime-a", "e1", created_at="2026-09-06T00:00:00Z"),
        _relation("runtime-b", "e2", created_at="2030-09-06T00:00:00Z"),
    )
    assert ordered == reversed_input == metadata

    local_before = _set(S1)
    local_after = _set(S1, S2)
    diluted_before = _set(S1)
    diluted_after = _set(S1, S2)
    assert relational_set_distance(local_before, local_after) == relational_set_distance(diluted_before, diluted_after)

    with pytest.raises(ValueError):
        _set(_relation("other", "other", requirement_id="r-other"))


def test_change_occurrence_is_exactly_distance_positive():
    cases = (
        (_set(), _set()),
        (_set(S1), _set(S1)),
        (_set(), _set(S1)),
        (_set(S1), _set(S2)),
        (_set(S1), _set(S1, S2)),
    )
    for previous, current in cases:
        assert change_occurrence(previous, current) is (relational_set_distance(previous, current) > 0)


def test_p1_to_p14_primitive_candidate_responses():
    empty = _set()
    one = _set(S1)
    two = _set(S1, S2)
    contradiction = _set(S1, C2)
    replaced = _set(C2)
    s1_element = next(iter(one))
    s2_element = next(iter(two - one))
    c2_element = next(iter(contradiction - one))
    basis_old = _set(S1)
    basis_new = _set(
        _relation("new-runtime-id", "e1", basis={"rule": "typed_field_present", "observed_value": "51000"})
    )
    temporal_old = _set(_relation("temporal", "e1", basis={"rule": "explicit_temporal_window", "observed_at": "t0"}))
    temporal_boundary = _set(_relation("temporal-new", "e1", basis={"rule": "explicit_temporal_window", "observed_at": "t0-minus-300"}))
    temporal_expired = _set(_relation("temporal", "e1", "NOT_APPLICABLE", basis={"rule": "explicit_temporal_window_outside"}))

    cases = {
        "P1": (one, one, (), (), Fraction(0, 1)),
        "P2": (one, _set(_relation("metadata", "e1", created_at="2030-01-01T00:00:00Z")), (), (), Fraction(0, 1)),
        "P3": (two, _set(S2, S1), (), (), Fraction(0, 1)),
        "P4": (one, two, (), (s2_element,), Fraction(1, 2)),
        "P5": (two, one, (s2_element,), (), Fraction(1, 2)),
        "P6": (one, empty, (s1_element,), (), Fraction(1, 1)),
        "P7": (one, contradiction, (), (c2_element,), Fraction(1, 2)),
        "P8": (contradiction, one, (c2_element,), (), Fraction(1, 2)),
        "P9": (one, replaced, (s1_element,), (c2_element,), Fraction(1, 1)),
        "P10": (basis_old, basis_new, (s1_element,), (next(iter(basis_new - basis_old)),), Fraction(1, 1)),
        "P11": (temporal_old, temporal_boundary, (next(iter(temporal_old)),), (next(iter(temporal_boundary)),), Fraction(1, 1)),
        "P12": (temporal_old, temporal_expired, (next(iter(temporal_old)),), (next(iter(temporal_expired)),), Fraction(1, 1)),
    }
    for name, (previous, current, expected_loss, expected_gain, expected_distance) in cases.items():
        assert relational_set_distance(previous, current) == expected_distance, name
        assert tuple(relational_loss(previous, current)) == tuple(sorted(expected_loss)), name
        assert tuple(relational_gain(previous, current)) == tuple(sorted(expected_gain)), name
        assert change_occurrence(previous, current) is (expected_distance > 0), name


def test_typed_delta_preserves_support_contradiction_and_temporal_partitions():
    previous = _set(S1)
    current = _set(_relation("different-relation-id", "e1", "CONTRADICTS"))
    delta = typed_relational_delta(previous, current)
    assert delta["removed_by_state"]["SATISFIES"] == tuple(sorted(previous))
    assert delta["added_by_state"]["CONTRADICTS"] == tuple(sorted(current))
    assert delta["changed_basis_by_state"][0]["previous_state"] == "SATISFIES"
    assert delta["changed_basis_by_state"][0]["current_state"] == "CONTRADICTS"
    assert tuple(relational_loss(previous, current)) == delta["removed_by_state"]["SATISFIES"]
    assert tuple(relational_gain(previous, current)) == delta["added_by_state"]["CONTRADICTS"]

    temporal_delta = typed_relational_delta(_set(S1), _set(N1))
    assert temporal_delta["removed_by_state"]["SATISFIES"]
    assert temporal_delta["added_by_state"]["NOT_APPLICABLE"]


def test_typed_delta_is_deterministic_and_replayable():
    previous = _set(S1, C2)
    current = _set(S2, N1)
    first = typed_relational_delta(previous, current)
    replay = typed_relational_delta(tuple(reversed(tuple(previous))), tuple(reversed(tuple(current))))
    assert first == replay


def test_restoration_is_categorical_prefix_only_and_lineage_scoped():
    empty = frozenset()
    support = _set(S1)
    contradiction = _set(S1, C2)

    assert relational_restoration((_point(0, empty),), _point(1, support)) is False
    assert relational_restoration((_point(0, support), _point(1, contradiction)), _point(2, support)) is True
    assert relational_restoration((_point(0, support), _point(1, empty)), _point(2, support)) is True
    assert relational_restoration((_point(0, support), _point(1, support)), _point(2, support)) is False

    with pytest.raises(ValueError):
        relational_restoration((_point(0, support, lineage="other"),), _point(1, support))
    with pytest.raises(ValueError):
        relational_restoration((_point(0, support, versions=(("e1", "v2"),)),), _point(1, support))
    with pytest.raises(ValueError):
        relational_restoration((_point(1, support),), _point(3, support))


def test_adversarial_a1_to_a14_cases():
    # A1: unrelated target requirements are excluded before local canonicalization.
    local_before = _set(S1)
    local_after = _set(S1, S2)
    unrelated = _relation("other", "other", requirement_id="r-other")
    assert relational_set_distance(local_before, local_after) == relational_set_distance(
        local_before,
        local_after,
    )
    with pytest.raises(ValueError):
        _set(S1, unrelated)

    # A2/A3: relation/evaluation/transition UUIDs are not candidate inputs.
    assert change_occurrence(_set(_relation("a", "e1")), _set(_relation("b", "e1"))) is False

    # A4: canonical object-key order and relation order are irrelevant.
    first = _set(_relation("a", "e1", basis={"z": 2, "a": 1}))
    second = _set(_relation("b", "e1", basis={"a": 1, "z": 2}))
    assert first == second

    # A5: distinct immutable artifacts remain distinct despite equal typed content.
    assert _set(_relation("a", "e1")) != _set(_relation("b", "e2"))

    # A6/A7: basis and relation-state changes are semantic changes.
    assert relational_set_distance(
        _set(_relation("a", "e1", basis={"value": "1"})),
        _set(_relation("b", "e1", basis={"value": "2"})),
    ) == 1
    assert relational_set_distance(_set(S1), _set(_relation("b", "e1", "CONTRADICTS"))) == 1

    # A8/A9/A10: empty set boundaries.
    assert relational_set_distance(_set(), _set()) == 0
    assert relational_set_distance(_set(), _set(S1)) == 1
    assert relational_set_distance(_set(S1), _set()) == 1

    # A11/A12: one local change in a large canonical set is not diluted.
    large = tuple(
        _relation(f"large-{index}", f"e-{index}")
        for index in range(40)
    )
    large_before = _set(*large)
    large_after = _set(*large, _relation("large-new", "e-new"))
    assert relational_set_distance(large_before, large_after) == Fraction(1, 41)
    large_removed = _set(*large[:-1])
    assert relational_set_distance(large_before, large_removed) == Fraction(1, 40)

    # A13/A14: restoration history rejects lineage and semantic-version crossing.
    with pytest.raises(ValueError):
        relational_restoration((_point(0, _set(S1), lineage="other"),), _point(1, _set(S1)))
    with pytest.raises(ValueError):
        relational_restoration(
            (_point(0, _set(S1), versions=(("e1", "v2"),)),),
            _point(1, _set(S1)),
        )
