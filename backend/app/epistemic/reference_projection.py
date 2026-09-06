"""Offline reference projections for the E2-C6 O_EPISTEMIC gate.

This module is deliberately outside the application runtime path.  It keeps
the exact Fraction source values and the adapter identity beside the float64
values sent to the certified local PRAMA Protokol v0.3.0 implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
import math
from typing import Literal

import numpy as np

from app.epistemic.phi_candidates import (
    CausalExpectationPoint,
    CausalTurnoverObservation,
    ExpectationEstimator,
    expanding_causal_mean_expectation,
    previous_value_expectation,
)
from app.prama_v030 import GammaRowV3, KernelConfigV3, KernelV3, project_v3


OMEGA_CONTRACT_VERSION = "OMEGA_EPI_EXPERIMENTAL_V0_1"
PV_EXPECTATION_CONTRACT = "EXPECTED_PV_V0_1"
ECM_EXPECTATION_CONTRACT = "EXPECTED_ECM_V0_1"
PV_ADAPTER_ID = "O_EPI_TURNOVER_PV_V0_1"
ECM_ADAPTER_ID = "O_EPI_TURNOVER_ECM_V0_1"
KERNEL_VERSION = "PRAMA_PROTOKOL_V0_3_0"
REFERENCE_STATUS = "CERTIFIED_DEFAULT_REFERENCE_ONLY"


@dataclass(frozen=True)
class ReferenceAdapter:
    identity: str
    expectation_contract: str
    estimator: ExpectationEstimator


PV_ADAPTER = ReferenceAdapter(
    identity=PV_ADAPTER_ID,
    expectation_contract=PV_EXPECTATION_CONTRACT,
    estimator=previous_value_expectation,
)
ECM_ADAPTER = ReferenceAdapter(
    identity=ECM_ADAPTER_ID,
    expectation_contract=ECM_EXPECTATION_CONTRACT,
    estimator=expanding_causal_mean_expectation,
)


@dataclass(frozen=True)
class SourceKernelMapping:
    source_event_index: int
    kernel_input_index: int | None
    kernel_state_index: int | None


@dataclass(frozen=True)
class ReferenceProjection:
    omega_contract: str
    expectation_contract: str
    adapter_identity: str
    semantic_version_tuple: tuple[tuple[str, str], ...]
    kernel_version: str
    config_status: str
    config: KernelConfigV3
    omega_exact: tuple[object, ...]
    expected_exact: tuple[object | None, ...]
    omega_float64: tuple[float, ...]
    expected_float64: tuple[float, ...]
    source_kernel_mapping: tuple[SourceKernelMapping, ...]
    streaming_rows: tuple[GammaRowV3, ...]
    batch_rows: tuple[dict[str, float | bool | int], ...]


def _ordered_population(
    observations: Sequence[CausalTurnoverObservation],
) -> tuple[CausalTurnoverObservation, ...]:
    if not observations:
        raise ValueError("reference projection requires a non-empty stream")
    ordered = tuple(sorted(observations, key=lambda item: item.event_index))
    first = ordered[0]
    if any(item.population_key() != first.population_key() for item in ordered):
        raise ValueError("reference stream crosses causal populations")
    if any(item.requirement_type != first.requirement_type for item in ordered):
        raise ValueError("reference stream changes requirement type")
    if any(left.event_index == right.event_index for left, right in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("reference stream contains duplicate event_index")
    return ordered


def _adapter_for(name: Literal["PV", "ECM"] | ReferenceAdapter) -> ReferenceAdapter:
    if isinstance(name, ReferenceAdapter):
        return name
    if name == "PV":
        return PV_ADAPTER
    if name == "ECM":
        return ECM_ADAPTER
    raise ValueError(f"unsupported reference adapter: {name!r}")


def project_reference(
    observations: Sequence[CausalTurnoverObservation],
    adapter: Literal["PV", "ECM"] | ReferenceAdapter,
    *,
    config: KernelConfigV3 | None = None,
) -> ReferenceProjection:
    """Run one offline reference projection without persistence or authority."""

    ordered = _ordered_population(observations)
    selected = _adapter_for(adapter)
    cfg = config if config is not None else KernelConfigV3()
    omega_exact = tuple(item.turnover for item in ordered)
    expected_exact = tuple(
        selected.estimator(
            ordered,
            CausalExpectationPoint.from_observation(item),
        )
        for item in ordered
    )
    omega_float64 = tuple(float(value) for value in omega_exact)
    expected_float64 = tuple(
        math.nan if value is None else float(value)
        for value in expected_exact
    )

    streaming_kernel = KernelV3(cfg)
    streaming_rows: list[GammaRowV3] = []
    mapping: list[SourceKernelMapping] = []
    for source_index, (omega, expected) in enumerate(zip(omega_float64, expected_float64, strict=True)):
        row = streaming_kernel.step(omega, expected, 0.0, None)
        if math.isnan(expected):
            if row is not None:
                raise AssertionError("leading warm-up unexpectedly emitted a row")
            mapping.append(SourceKernelMapping(ordered[source_index].event_index, None, None))
            continue
        if row is None:
            raise AssertionError("finite expectation did not emit a row")
        streaming_rows.append(row)
        mapping.append(
            SourceKernelMapping(
                source_event_index=ordered[source_index].event_index,
                kernel_input_index=row.input_index,
                kernel_state_index=row.state_index,
            )
        )

    batch = project_v3(
        np.asarray(omega_float64, dtype=np.float64),
        np.asarray(expected_float64, dtype=np.float64),
        cfg,
        u_lambda=np.zeros(len(ordered), dtype=np.float64),
        sigma_op=None,
    )

    return ReferenceProjection(
        omega_contract=OMEGA_CONTRACT_VERSION,
        expectation_contract=selected.expectation_contract,
        adapter_identity=selected.identity,
        semantic_version_tuple=ordered[0].semantic_version_tuple,
        kernel_version=KERNEL_VERSION,
        config_status=REFERENCE_STATUS,
        config=cfg,
        omega_exact=omega_exact,
        expected_exact=expected_exact,
        omega_float64=omega_float64,
        expected_float64=expected_float64,
        source_kernel_mapping=tuple(mapping),
        streaming_rows=tuple(streaming_rows),
        batch_rows=tuple(batch.rows()),
    )
