"""E2-C6 offline reference projection validation."""

from __future__ import annotations

from fractions import Fraction
import math

import pytest

from app.epistemic.phi_candidates import CausalTurnoverObservation
from app.epistemic.phi_candidates import canonical_relation_set, relational_set_distance
from app.epistemic.reference_projection import (
    ECM_ADAPTER,
    ECM_ADAPTER_ID,
    OMEGA_CONTRACT_VERSION,
    PV_ADAPTER,
    PV_ADAPTER_ID,
    project_reference,
)


VERSION = (("e1", "v1"), ("e2", "v1"))


def _observations(values: list[float | int], *, lineage: str = "L1", target: str = "T1"):
    return tuple(
        CausalTurnoverObservation(
            trajectory_lineage_id=lineage,
            target_id=target,
            requirement_id="R1",
            requirement_type="relational_surface",
            semantic_version_tuple=VERSION,
            event_index=index,
            turnover=value,
        )
        for index, value in enumerate(values)
    )


SEQUENCES = (
    ("K1", [0, 0, 0, 0]),
    ("K2", [1, 0, 0, 0]),
    ("K3", [0, 1, 0, 0]),
    ("K4", [0, 1, 0, 1, 0, 1]),
    ("K5", [0.1, 0.1, 0.1, 0.9]),
    ("K6", [0.9, 0.9, 0.9, 0.1]),
    ("K7", [0.2, 0.4, 0.6, 0.8]),
    ("K8", [0.8, 0.6, 0.4, 0.2]),
    ("K9", [0] * 30 + [1]),
    ("K10", [1] * 30 + [0]),
)


def _assert_close(left: float, right: float) -> None:
    assert math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _assert_rows_equal(streaming, batch) -> None:
    assert len(streaming) == len(batch)
    for stream_row, batch_row in zip(streaming, batch, strict=True):
        stream_dict = stream_row.as_dict()
        assert stream_dict.keys() == batch_row.keys()
        for key in stream_dict:
            if isinstance(stream_dict[key], bool) or isinstance(stream_dict[key], int):
                assert stream_dict[key] == batch_row[key]
            else:
                _assert_close(float(stream_dict[key]), float(batch_row[key]))


def _assert_equations(projection) -> None:
    cfg = projection.config
    r = cfg.r
    xi = 0.0
    accumulated = 0.0
    lambda_value = cfg.lambda_0
    theta = cfg.theta_scale * cfg.lambda_0
    ring: list[float] = []
    smooth_previous: float | None = None
    row_index = 0

    for omega, expected in zip(
        projection.omega_float64,
        projection.expected_float64,
        strict=True,
    ):
        if math.isnan(expected):
            continue
        row = projection.streaming_rows[row_index]
        row_index += 1

        delta = abs(omega - expected) / (expected + 1.0)
        delta_tilde = delta / cfg.delta_ref
        error = max(xi - theta, 0.0)
        accumulated_next = accumulated + cfg.h * error
        lambda_raw = lambda_value - cfg.kappa_v3 * cfg.h * accumulated_next
        lambda_next = min(cfg.lambda_max, max(cfg.lambda_min, lambda_raw))
        theta_next = cfg.theta_scale * lambda_next
        xi_next = r * xi + (1.0 - r) * delta_tilde
        margin = theta_next - xi_next

        ring.append(margin)
        if len(ring) > cfg.g_smooth:
            ring.pop(0)
        smooth = sum(ring) / len(ring)
        trend = 0.0 if smooth_previous is None else smooth - smooth_previous

        _assert_close(row.delta, delta)
        _assert_close(row.delta_tilde, delta_tilde)
        _assert_close(row.e, error)
        _assert_close(row.A, accumulated_next)
        _assert_close(row.lambda_, lambda_next)
        _assert_close(row.theta, theta_next)
        _assert_close(row.xi, xi_next)
        _assert_close(row.M, margin)
        _assert_close(row.G, trend)
        assert row.u_lambda == 0.0
        assert row.sigma_op is (omega > 0.0)

        xi = xi_next
        accumulated = accumulated_next
        lambda_value = lambda_next
        theta = theta_next
        smooth_previous = smooth


@pytest.mark.parametrize("name,values", SEQUENCES)
@pytest.mark.parametrize("adapter", (PV_ADAPTER, ECM_ADAPTER), ids=("PV", "ECM"))
def test_reference_projection_streaming_batch_and_equations(name, values, adapter):
    projection = project_reference(_observations(values), adapter)

    assert projection.omega_contract == OMEGA_CONTRACT_VERSION
    assert projection.adapter_identity == adapter.identity
    assert projection.config_status == "CERTIFIED_DEFAULT_REFERENCE_ONLY"
    assert len(projection.source_kernel_mapping) == len(values)
    assert projection.source_kernel_mapping[0].kernel_input_index is None
    assert projection.source_kernel_mapping[0].kernel_state_index is None
    assert projection.source_kernel_mapping[1].kernel_input_index == 0
    assert projection.source_kernel_mapping[1].kernel_state_index == 1
    assert all(math.isfinite(value) for value in projection.omega_float64)
    assert all(
        math.isnan(value) if exact is None else math.isfinite(value)
        for exact, value in zip(projection.expected_exact, projection.expected_float64, strict=True)
    )
    _assert_rows_equal(projection.streaming_rows, projection.batch_rows)
    _assert_equations(projection)


def test_warmup_exclusion_and_no_missing_after_start():
    projection = project_reference(_observations([0, 1, 0]), PV_ADAPTER)
    assert projection.source_kernel_mapping == (
        projection.source_kernel_mapping[0],
        projection.source_kernel_mapping[1],
        projection.source_kernel_mapping[2],
    )
    assert projection.source_kernel_mapping[0].source_event_index == 0
    assert projection.source_kernel_mapping[1].source_event_index == 1
    assert projection.source_kernel_mapping[1].kernel_input_index == 0
    assert projection.source_kernel_mapping[1].kernel_state_index == 1
    assert all(row.valid for row in projection.streaming_rows)
    assert all(value is not None for value in projection.expected_exact[1:])


def test_exact_values_are_retained_alongside_float64_inputs():
    projection = project_reference(_observations([0.1, 0.2, 0.3]), ECM_ADAPTER)
    assert projection.omega_exact == (Fraction(1, 10), Fraction(1, 5), Fraction(3, 10))
    assert projection.expected_exact == (None, Fraction(1, 10), Fraction(3, 20))
    assert projection.omega_float64 == tuple(float(value) for value in projection.omega_exact)
    assert projection.expected_float64[0] != projection.expected_float64[0]
    assert projection.expected_float64[1] == float(Fraction(1, 10))


def test_pv_ecm_adapter_identity_and_gamma_separation():
    values = _observations([1, 0, 0, 0])
    pv = project_reference(values, PV_ADAPTER)
    ecm = project_reference(values, ECM_ADAPTER)

    assert pv.omega_exact == ecm.omega_exact
    assert pv.adapter_identity == PV_ADAPTER_ID
    assert ecm.adapter_identity == ECM_ADAPTER_ID
    assert pv.expected_exact != ecm.expected_exact
    assert pv.streaming_rows[1].delta != ecm.streaming_rows[1].delta


def test_reference_projection_replay_is_exact_and_order_invariant():
    observations = _observations([0.2, 0.4, 0.6, 0.8])
    for adapter in (PV_ADAPTER, ECM_ADAPTER):
        first = project_reference(observations, adapter)
        replay = project_reference(tuple(reversed(observations)), adapter)
        assert first.adapter_identity == replay.adapter_identity
        assert first.omega_exact == replay.omega_exact
        assert first.expected_exact == replay.expected_exact
        assert first.source_kernel_mapping == replay.source_kernel_mapping
        _assert_rows_equal(first.streaming_rows, replay.batch_rows)


def test_default_dynamic_degeneracy_and_channel_classification():
    projections = [
        project_reference(_observations(values), adapter)
        for _, values in SEQUENCES
        for adapter in (PV_ADAPTER, ECM_ADAPTER)
    ]
    rows = [row for projection in projections for row in projection.streaming_rows]

    assert rows
    assert all(0.0 <= row.delta <= 1.0 for row in rows)
    assert all(0.0 <= row.delta_tilde <= 1.0 for row in rows)
    assert all(0.0 <= row.xi < 1.0 for row in rows)
    assert all(row.e == 0.0 for row in rows)
    assert all(row.A == 0.0 for row in rows)
    assert all(row.lambda_ == 1.0 for row in rows)
    assert all(row.theta == 2.0 for row in rows)
    assert all(1.0 < row.M <= 2.0 for row in rows)
    assert any(row.G != 0.0 for row in rows)


def _relation(evidence_id: str, state: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "relation_state": state,
        "relation_basis": {"rule": "fixture_relation", "evidence": evidence_id},
    }


def _surface(*relations: dict[str, object]):
    return canonical_relation_set(
        relations,
        target_id="fixture-target",
        requirement_id="fixture-requirement",
        requirement_type="quote_currency",
    )


def test_actual_e1p_e2c_fixture_trajectory_is_projected():
    support = _relation("e1", "SATISFIES")
    contradiction = _relation("e2", "CONTRADICTS")
    surfaces = (
        _surface(),
        _surface(support),
        _surface(support, contradiction),
        _surface(support),
    )
    omega = tuple(
        relational_set_distance(previous, current)
        for previous, current in zip(surfaces, surfaces[1:])
    )
    observations = tuple(
        CausalTurnoverObservation(
            trajectory_lineage_id="fixture-e2c-lineage",
            target_id="fixture-target",
            requirement_id="fixture-requirement",
            requirement_type="quote_currency",
            semantic_version_tuple=VERSION,
            event_index=index,
            turnover=value,
        )
        for index, value in enumerate(omega)
    )

    projection = project_reference(observations, PV_ADAPTER)
    assert projection.omega_exact == (Fraction(1, 1), Fraction(1, 2), Fraction(1, 2))
    assert projection.source_kernel_mapping[0].kernel_state_index is None
    assert len(projection.streaming_rows) == 2
