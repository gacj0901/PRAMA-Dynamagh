"""E2-C4-P causal expectation validation, before any PRAMA adapter."""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.epistemic.phi_candidates import (
    CausalExpectationPoint,
    CausalTurnoverObservation,
    causal_expectation_stream,
    expanding_causal_mean_expectation,
    previous_value_expectation,
)


VERSION_V1 = (("e1", "v1"), ("e2", "v1"))
VERSION_V2 = (("e1", "v2"), ("e2", "v1"))


def _observations(
    values: list[float | int],
    *,
    lineage: str = "L1",
    target: str = "T1",
    requirement: str = "R1",
    requirement_type: str = "relational_surface",
    version: tuple[tuple[str, str], ...] = VERSION_V1,
    start: int = 0,
) -> tuple[CausalTurnoverObservation, ...]:
    return tuple(
        CausalTurnoverObservation(
            trajectory_lineage_id=lineage,
            target_id=target,
            requirement_id=requirement,
            requirement_type=requirement_type,
            semantic_version_tuple=version,
            event_index=start + index,
            turnover=value,
        )
        for index, value in enumerate(values)
    )


def _expected_point(
    event_index: int,
    *,
    lineage: str = "L1",
    target: str = "T1",
    requirement: str = "R1",
    requirement_type: str = "relational_surface",
    version: tuple[tuple[str, str], ...] = VERSION_V1,
) -> CausalExpectationPoint:
    return CausalExpectationPoint(
        trajectory_lineage_id=lineage,
        target_id=target,
        requirement_id=requirement,
        requirement_type=requirement_type,
        semantic_version_tuple=version,
        event_index=event_index,
    )


def _stream(values: list[float | int], estimator):
    return causal_expectation_stream(_observations(values), estimator)


@pytest.mark.parametrize(
    ("name", "values", "pv", "ecm"),
    (
        ("S1", [0, 0, 0, 0], [None, 0, 0, 0], [None, 0, 0, 0]),
        ("S2", [1, 0, 0, 0], [None, 1, 0, 0], [None, 1, Fraction(1, 2), Fraction(1, 3)]),
        ("S3", [0, 1, 0, 0], [None, 0, 1, 0], [None, 0, Fraction(1, 2), Fraction(1, 3)]),
        (
            "S4",
            [0, 1, 0, 1, 0, 1],
            [None, 0, 1, 0, 1, 0],
            [None, 0, Fraction(1, 2), Fraction(1, 3), Fraction(1, 2), Fraction(2, 5)],
        ),
        ("S5", [0.1, 0.1, 0.1, 0.9], [None, Fraction(1, 10), Fraction(1, 10), Fraction(1, 10)], [None, Fraction(1, 10), Fraction(1, 10), Fraction(1, 10)]),
        ("S6", [0.9, 0.9, 0.9, 0.1], [None, Fraction(9, 10), Fraction(9, 10), Fraction(9, 10)], [None, Fraction(9, 10), Fraction(9, 10), Fraction(9, 10)]),
        ("S7", [0.2, 0.4, 0.6, 0.8], [None, Fraction(1, 5), Fraction(2, 5), Fraction(3, 5)], [None, Fraction(1, 5), Fraction(3, 10), Fraction(2, 5)]),
        ("S8", [0.8, 0.6, 0.4, 0.2], [None, Fraction(4, 5), Fraction(3, 5), Fraction(2, 5)], [None, Fraction(4, 5), Fraction(7, 10), Fraction(3, 5)]),
        ("S9", [0.5], [None], [None]),
        ("S10", [0, 0, 0, 0, 0, 1], [None, 0, 0, 0, 0, 0], [None, 0, 0, 0, 0, 0]),
        ("S11", [1, 1, 1, 1, 1, 0], [None, 1, 1, 1, 1, 1], [None, 1, 1, 1, 1, 1]),
    ),
)
def test_required_sequences_use_only_strict_prior(name, values, pv, ecm):
    assert _stream(values, previous_value_expectation) == tuple(pv), name
    assert _stream(values, expanding_causal_mean_expectation) == tuple(ecm), name


def test_lineage_isolation_and_event_index_restart():
    l1 = _observations([1, 1], lineage="L1")
    l2 = _observations([0, 0], lineage="L2")
    history = l1 + l2

    assert previous_value_expectation(history, _expected_point(2, lineage="L1")) == 1
    assert previous_value_expectation(history, _expected_point(2, lineage="L2")) == 0
    assert expanding_causal_mean_expectation(history, _expected_point(2, lineage="L1")) == 1
    assert expanding_causal_mean_expectation(history, _expected_point(2, lineage="L2")) == 0


def test_version_isolation_resets_history():
    v1 = _observations([1, 0], version=VERSION_V1)
    v2 = _observations([0, 1], version=VERSION_V2, start=0)
    history = v1 + v2

    assert previous_value_expectation(history, _expected_point(0, version=VERSION_V2)) is None
    assert expanding_causal_mean_expectation(history, _expected_point(0, version=VERSION_V2)) is None
    assert previous_value_expectation(history, _expected_point(1, version=VERSION_V2)) == 0
    assert expanding_causal_mean_expectation(history, _expected_point(1, version=VERSION_V2)) == 0


def test_cross_target_same_requirement_type_does_not_pool():
    target_a = _observations([1, 1], target="A")
    target_b = _observations([0, 0], target="B")
    history = target_a + target_b

    assert previous_value_expectation(history, _expected_point(2, target="A")) == 1
    assert previous_value_expectation(history, _expected_point(2, target="B")) == 0
    assert expanding_causal_mean_expectation(history, _expected_point(2, target="A")) == 1
    assert expanding_causal_mean_expectation(history, _expected_point(2, target="B")) == 0


def test_prefix_invariance_excludes_current_and_future_suffix():
    prefix = _observations([Fraction(1, 5), Fraction(2, 5)])
    current = _observations([Fraction(3, 5)], start=2)
    future_a = _observations([Fraction(4, 5)], start=3)
    future_b = _observations([0], start=3)
    point = _expected_point(2)

    history_a = prefix + current + future_a
    history_b = prefix + _observations([Fraction(4, 5)], start=2) + future_b
    assert previous_value_expectation(history_a, point) == previous_value_expectation(history_b, point) == Fraction(2, 5)
    assert expanding_causal_mean_expectation(history_a, point) == expanding_causal_mean_expectation(history_b, point) == Fraction(3, 10)


def test_zero_is_distinct_from_unavailable():
    history = _observations([0])
    assert previous_value_expectation(history, _expected_point(0)) is None
    assert expanding_causal_mean_expectation(history, _expected_point(0)) is None
    assert previous_value_expectation(history, _expected_point(1)) == 0
    assert expanding_causal_mean_expectation(history, _expected_point(1)) == 0


def test_abrupt_change_is_not_ranked_by_the_estimators():
    low_high = _observations([0.1, 0.1, 0.1, 0.9])
    high_low = _observations([0.9, 0.9, 0.9, 0.1])

    assert previous_value_expectation(low_high, _expected_point(3)) == Fraction(1, 10)
    assert expanding_causal_mean_expectation(low_high, _expected_point(3)) == Fraction(1, 10)
    assert previous_value_expectation(low_high, _expected_point(4)) == Fraction(9, 10)
    assert expanding_causal_mean_expectation(low_high, _expected_point(4)) == Fraction(3, 10)
    assert previous_value_expectation(high_low, _expected_point(3)) == Fraction(9, 10)
    assert expanding_causal_mean_expectation(high_low, _expected_point(3)) == Fraction(9, 10)
    assert previous_value_expectation(high_low, _expected_point(4)) == Fraction(1, 10)
    assert expanding_causal_mean_expectation(high_low, _expected_point(4)) == Fraction(7, 10)


def test_restoration_collision_and_artifact_attribution_are_not_inferred():
    restoration_distance_history = _observations([0, 1, 0, 1])
    non_restoration_distance_history = _observations([0, 1, 0, 1], lineage="L2")
    point_l1 = _expected_point(4, lineage="L1")
    point_l2 = _expected_point(4, lineage="L2")

    assert previous_value_expectation(restoration_distance_history, point_l1) == previous_value_expectation(non_restoration_distance_history, point_l2) == 1
    assert expanding_causal_mean_expectation(restoration_distance_history, point_l1) == expanding_causal_mean_expectation(non_restoration_distance_history, point_l2) == Fraction(1, 2)

    repeated_artifacts = _observations([0, 0, 1])
    assert causal_expectation_stream(repeated_artifacts, previous_value_expectation) == (None, 0, 0)
    assert causal_expectation_stream(repeated_artifacts, expanding_causal_mean_expectation) == (None, 0, 0)


def test_order_invariance_replay_and_uuid_independence():
    observations = _observations([0.2, 0.4, 0.6, 0.8])
    reversed_history = tuple(reversed(observations))
    for estimator in (previous_value_expectation, expanding_causal_mean_expectation):
        assert causal_expectation_stream(observations, estimator) == causal_expectation_stream(reversed_history, estimator)
        assert causal_expectation_stream(observations, estimator) == causal_expectation_stream(observations, estimator)


def test_pv_and_ecm_are_distinct_expectation_hypotheses():
    history = _observations([1, 0])
    point = _expected_point(2)
    assert previous_value_expectation(history, point) == 0
    assert expanding_causal_mean_expectation(history, point) == Fraction(1, 2)


def test_invalid_observation_and_duplicate_event_fail_closed():
    with pytest.raises(ValueError):
        _observations([1.1])

    duplicate = _observations([0], start=0) + _observations([1], start=0)
    with pytest.raises(ValueError):
        previous_value_expectation(duplicate, _expected_point(1))
