"""PRAMA Protokol v0.3.0 universal activation kernel.

This module preserves the v0.2.1 API as a compatibility surface while adding
the certified v0.3.0 state machine. Input ``k`` produces state ``k+1``.
Leading expectation warm-up rows are excluded; any missing or non-finite
value after emission starts fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Iterable

import numpy as np

__all__ = [
    "GammaRowV3",
    "GammaV3",
    "KernelConfigV3",
    "KernelV3",
    "NumericAuditV3",
    "V3ProjectionError",
    "project_v3",
]


class V3ProjectionError(ValueError):
    """Fail-closed input or configuration error for the v0.3 projection."""


@dataclass(frozen=True)
class KernelConfigV3:
    """Frozen v0.3 kernel parameters, measured in stream bins."""

    h: float = 1.0
    tau: float = 336.0
    theta_scale: float = 2.0
    lambda_0: float = 1.0
    lambda_min: float = 0.1
    lambda_max: float = 1.0
    kappa_v3: float = 9.957514604354753e-7
    g_smooth: int = 24
    delta_ref: float = 1.0

    def __post_init__(self) -> None:
        scalar_fields = (
            "h",
            "tau",
            "theta_scale",
            "lambda_0",
            "lambda_min",
            "lambda_max",
            "kappa_v3",
            "delta_ref",
        )
        for name in scalar_fields:
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise V3ProjectionError(f"{name} must be finite")
        if self.h <= 0.0:
            raise V3ProjectionError("h must be > 0")
        if self.tau <= 0.0:
            raise V3ProjectionError("tau must be > 0")
        if self.theta_scale <= 0.0:
            raise V3ProjectionError("theta_scale must be > 0")
        if self.lambda_min < 0.0 or self.lambda_min > self.lambda_max:
            raise V3ProjectionError("lambda bounds are invalid")
        if not self.lambda_min <= self.lambda_0 <= self.lambda_max:
            raise V3ProjectionError("lambda_0 must lie within lambda bounds")
        if self.kappa_v3 < 0.0:
            raise V3ProjectionError("kappa_v3 must be >= 0")
        if not isinstance(self.g_smooth, int) or isinstance(self.g_smooth, bool):
            raise V3ProjectionError("g_smooth must be an integer")
        if self.g_smooth <= 0:
            raise V3ProjectionError("g_smooth must be > 0")
        if self.delta_ref <= 0.0:
            raise V3ProjectionError("delta_ref must be > 0")

    @property
    def r(self) -> float:
        """Derived causal retention; it is never a configurable parameter."""

        return math.exp(-self.h / self.tau)


@dataclass(frozen=True)
class GammaRowV3:
    """One emitted row: input ``k`` and the resulting state ``k+1``."""

    delta: float
    delta_tilde: float
    e: float
    xi: float
    A: float
    lambda_: float
    theta: float
    M: float
    G: float
    u_lambda: float
    sigma_op: bool
    valid: bool
    input_index: int
    state_index: int

    def as_dict(self) -> dict[str, float | bool | int]:
        out = {field.name: getattr(self, field.name) for field in fields(self)}
        out["lambda"] = out.pop("lambda_")
        return out


@dataclass(frozen=True)
class GammaV3:
    """Column-major v0.3 trajectory with the frozen ``Gamma_v3`` schema."""

    delta: np.ndarray
    delta_tilde: np.ndarray
    e: np.ndarray
    xi: np.ndarray
    A: np.ndarray
    lambda_: np.ndarray
    theta: np.ndarray
    M: np.ndarray
    G: np.ndarray
    u_lambda: np.ndarray
    sigma_op: np.ndarray
    valid: np.ndarray
    input_index: np.ndarray
    state_index: np.ndarray

    @classmethod
    def from_rows(cls, rows: Iterable[GammaRowV3]) -> "GammaV3":
        materialized = list(rows)
        float_field_names = (
            "delta",
            "delta_tilde",
            "e",
            "xi",
            "A",
            "lambda_",
            "theta",
            "M",
            "G",
            "u_lambda",
        )
        columns: dict[str, np.ndarray] = {
            name: np.asarray([getattr(row, name) for row in materialized], dtype=np.float64)
            for name in float_field_names
        }
        columns["sigma_op"] = np.asarray(
            [row.sigma_op for row in materialized], dtype=np.bool_
        )
        columns["valid"] = np.asarray(
            [row.valid for row in materialized], dtype=np.bool_
        )
        columns["input_index"] = np.asarray(
            [row.input_index for row in materialized], dtype=np.int64
        )
        columns["state_index"] = np.asarray(
            [row.state_index for row in materialized], dtype=np.int64
        )
        return cls(**columns)

    def __len__(self) -> int:
        return int(self.delta.size)

    def as_dict(self) -> dict[str, np.ndarray]:
        out = {field.name: getattr(self, field.name) for field in fields(self)}
        out["lambda"] = out.pop("lambda_")
        return out

    def rows(self) -> list[dict[str, float | bool | int]]:
        mapping = self.as_dict()
        return [
            {
                name: column[i].item()
                if isinstance(column[i], np.generic)
                else column[i]
                for name, column in mapping.items()
            }
            for i in range(len(self))
        ]


@dataclass(frozen=True)
class NumericAuditV3:
    """Read-only numerical ledger for a v0.3.0 streaming state."""

    emitted_count: int
    resummation_count: int
    ring_len: int
    ring_sum: float
    smooth_m: float | None
    lambda_sum_A: float
    lambda_sum_u: float
    lambda_sum_pi: float
    lambda_step_residual: float
    lambda_ledger_residual: float


class KernelV3:
    """Stateful streaming implementation of the frozen v0.3 recursion."""

    def __init__(self, cfg: KernelConfigV3 | None = None) -> None:
        self.cfg = cfg if cfg is not None else KernelConfigV3()
        self._r = self.cfg.r
        self._xi = 0.0
        self._A = 0.0
        self._lambda = self.cfg.lambda_0
        self._theta = self.cfg.theta_scale * self.cfg.lambda_0
        self._started = False
        self._input_index = 0
        self._m_ring = [0.0] * self.cfg.g_smooth
        self._ring_pos = 0
        self._ring_len = 0
        self._ring_sum = 0.0
        self._smooth_m_prev: float | None = None
        self._resummation_count = 0
        self._lambda_sum_A = 0.0
        self._lambda_sum_u = 0.0
        self._lambda_sum_pi = 0.0
        self._lambda_step_residual = 0.0
        self._lambda_ledger_residual = 0.0

    @property
    def started(self) -> bool:
        return self._started

    @property
    def numeric_audit(self) -> NumericAuditV3:
        """Return the current ring and lambda ledgers without mutating state."""

        return NumericAuditV3(
            emitted_count=self._input_index,
            resummation_count=self._resummation_count,
            ring_len=self._ring_len,
            ring_sum=self._ring_sum,
            smooth_m=self._smooth_m_prev,
            lambda_sum_A=self._lambda_sum_A,
            lambda_sum_u=self._lambda_sum_u,
            lambda_sum_pi=self._lambda_sum_pi,
            lambda_step_residual=self._lambda_step_residual,
            lambda_ledger_residual=self._lambda_ledger_residual,
        )

    def step(
        self,
        omega: float,
        expected: float,
        u_lambda: float = 0.0,
        sigma_op: bool | None = None,
    ) -> GammaRowV3 | None:
        """Consume one source row and emit one state, or exclude warm-up.

        A leading ``expected=NaN`` row is excluded before state initialization.
        Once one state has been emitted, ``NaN`` fails closed.  Validation is
        completed before any state mutation.
        """

        omega_value = float(omega)
        expected_value = float(expected)
        u_value = float(u_lambda)

        if math.isnan(expected_value):
            if self._started:
                raise V3ProjectionError("internal_missing_after_start")
            return None
        if not math.isfinite(expected_value):
            raise V3ProjectionError("expected must be finite")
        if not math.isfinite(omega_value):
            raise V3ProjectionError("omega must be finite")
        if expected_value < 0.0:
            raise V3ProjectionError("expected must be >= 0")
        if not math.isfinite(u_value) or u_value < 0.0:
            raise V3ProjectionError("u_lambda must be finite and >= 0")
        if sigma_op is not None and not isinstance(sigma_op, (bool, np.bool_)):
            raise V3ProjectionError("sigma_op must be boolean")

        delta = abs(omega_value - expected_value) / (expected_value + 1.0)
        delta_tilde = delta / self.cfg.delta_ref

        e = max(self._xi - self._theta, 0.0)
        a_next = self._A + self.cfg.h * e

        lambda_raw = (
            self._lambda
            - self.cfg.kappa_v3 * self.cfg.h * a_next
            + self.cfg.h * u_value
        )
        lambda_next = min(self.cfg.lambda_max, max(self.cfg.lambda_min, lambda_raw))
        theta_next = self.cfg.theta_scale * lambda_next

        xi_next = self._r * self._xi + (1.0 - self._r) * delta_tilde
        margin = theta_next - xi_next

        ring_sum = self._ring_sum
        ring_len = self._ring_len
        ring_pos = self._ring_pos
        if ring_len == len(self._m_ring):
            ring_sum -= self._m_ring[ring_pos]
        else:
            ring_len += 1
        ring_sum += margin
        next_ring_pos = (ring_pos + 1) % len(self._m_ring)
        emitted_count = self._input_index + 1
        resummation_count = self._resummation_count
        if emitted_count % len(self._m_ring) == 0:
            # Rebuild after insertion, in logical order from oldest to newest.
            # The candidate value is read without mutating the live ring so a
            # later validation failure still leaves the stream state intact.
            ring_sum = 0.0
            oldest = next_ring_pos if ring_len == len(self._m_ring) else 0
            for offset in range(ring_len):
                position = (oldest + offset) % len(self._m_ring)
                value = margin if position == ring_pos else self._m_ring[position]
                ring_sum = ring_sum + value
            resummation_count += 1
        smooth_m = ring_sum / float(ring_len)
        g = 0.0 if self._smooth_m_prev is None else smooth_m - self._smooth_m_prev

        pi = lambda_next - lambda_raw
        lambda_sum_A = self._lambda_sum_A + a_next
        lambda_sum_u = self._lambda_sum_u + u_value
        lambda_sum_pi = self._lambda_sum_pi + pi
        lambda_step_residual = (
            lambda_next
            - self._lambda
            + self.cfg.kappa_v3 * self.cfg.h * a_next
            - self.cfg.h * u_value
            - pi
        )
        lambda_ledger_residual = (
            lambda_next
            - self.cfg.lambda_0
            + self.cfg.kappa_v3 * self.cfg.h * lambda_sum_A
            - self.cfg.h * lambda_sum_u
            - lambda_sum_pi
        )

        computed = (
            delta,
            delta_tilde,
            e,
            a_next,
            lambda_raw,
            lambda_next,
            theta_next,
            xi_next,
            margin,
            ring_sum,
            smooth_m,
            g,
            pi,
            lambda_sum_A,
            lambda_sum_u,
            lambda_sum_pi,
            lambda_step_residual,
            lambda_ledger_residual,
        )
        if not all(math.isfinite(value) for value in computed):
            raise V3ProjectionError("non-finite arithmetic result")

        operational = omega_value > 0.0 if sigma_op is None else bool(sigma_op)
        k = self._input_index
        row = GammaRowV3(
            delta=delta,
            delta_tilde=delta_tilde,
            e=e,
            xi=xi_next,
            A=a_next,
            lambda_=lambda_next,
            theta=theta_next,
            M=margin,
            G=g,
            u_lambda=u_value,
            sigma_op=operational,
            valid=True,
            input_index=k,
            state_index=k + 1,
        )

        self._m_ring[ring_pos] = margin
        self._ring_pos = next_ring_pos
        self._ring_len = ring_len
        self._ring_sum = ring_sum
        self._smooth_m_prev = smooth_m
        self._resummation_count = resummation_count
        self._lambda_sum_A = lambda_sum_A
        self._lambda_sum_u = lambda_sum_u
        self._lambda_sum_pi = lambda_sum_pi
        self._lambda_step_residual = lambda_step_residual
        self._lambda_ledger_residual = lambda_ledger_residual
        self._xi = xi_next
        self._A = a_next
        self._lambda = lambda_next
        self._theta = theta_next
        self._input_index += 1
        self._started = True
        return row


def _one_dimensional(name: str, values: object, dtype: object) -> np.ndarray:
    array = np.asarray(values, dtype=dtype)
    if array.ndim != 1:
        raise V3ProjectionError(f"{name} must be one-dimensional")
    return array


def project_v3(
    omega: np.ndarray,
    expected: np.ndarray,
    cfg: KernelConfigV3 | None = None,
    u_lambda: np.ndarray | None = None,
    sigma_op: np.ndarray | None = None,
) -> GammaV3:
    """Batch projection implemented by the certified streaming state machine."""

    obs = _one_dimensional("omega", omega, np.float64)
    exp = _one_dimensional("expected", expected, np.float64)
    if obs.size == 0:
        raise V3ProjectionError("inputs must be non-empty")
    if obs.shape != exp.shape:
        raise V3ProjectionError("omega and expected must have the same shape")

    if u_lambda is None:
        controls = np.zeros(obs.size, dtype=np.float64)
    else:
        controls = _one_dimensional("u_lambda", u_lambda, np.float64)
        if controls.shape != obs.shape:
            raise V3ProjectionError("u_lambda must match omega")

    if sigma_op is None:
        operational: np.ndarray | None = None
    else:
        raw_sigma = np.asarray(sigma_op)
        if raw_sigma.ndim != 1 or raw_sigma.shape != obs.shape:
            raise V3ProjectionError("sigma_op must match omega")
        if raw_sigma.dtype.kind != "b":
            raise V3ProjectionError("sigma_op must contain booleans")
        operational = raw_sigma.astype(np.bool_, copy=False)

    kernel = KernelV3(cfg)
    rows: list[GammaRowV3] = []
    for source_index in range(obs.size):
        sigma_value = None if operational is None else bool(operational[source_index])
        row = kernel.step(
            obs[source_index],
            exp[source_index],
            controls[source_index],
            sigma_value,
        )
        if row is not None:
            rows.append(row)
    if not rows:
        raise V3ProjectionError("no_valid_rows")
    return GammaV3.from_rows(rows)
