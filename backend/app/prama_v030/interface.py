"""PRAMA Protokol — Observation Interface (O_D).

The only consumer-specific component of the protocol (specification §6).

A domain joins the Protokol by producing two arrays:

    omega    : the dimensionless, normalized observable stream ω(t)   (C1, N1)
    expected : its strictly causal expectation ω̂(t)                   (C2, C3)

This module provides the contract as a base class and one universal,
domain-free expectation builder:

    CausalConditionalMean — the strictly causal conditional mean of the
    stream given any categorical context, with fallback to the causal global
    mean during warm-up.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
__all__ = ["ObservationInterface", "CausalConditionalMean", "causal_conditional_mean"]


class ObservationInterface(ABC):
    """Contract for a consumer's observation interface (specification §6).

    Implementations MUST satisfy:
      C1  Strict observability — only externally observable events.
      C2  Strict causality     — ω̂(t) depends on the strict past only.
      C3  Genuine decoupling   — ω̂ is the system's own expected behavior,
                                 never a constant or a copy of activity.
      N1  Scale invariance     — ω is dimensionless and an explicit
                                 normalization is part of this interface.
      C5  No retro-fitting     — nothing here is tuned on outcome labels.

    Conformance is checked mechanically by `prama_protokol.compliance`.
    """

    @abstractmethod
    def stream(self) -> np.ndarray:
        """Return the normalized observable stream ω(t) (C1, N1)."""

    @abstractmethod
    def expectation(self) -> np.ndarray:
        """Return the strictly causal expectation ω̂(t) (C2, C3).

        Warm-up positions with no causal expectation yet MUST be NaN.
        """


def causal_conditional_mean(
    values: np.ndarray,
    context: np.ndarray,
    min_context_count: int = 10,
    min_global_count: int = 720,
) -> np.ndarray:
    """Strictly causal conditional mean of `values` given a categorical context.

    At each position i, the expectation uses ONLY positions j < i:
      - the running mean of past values sharing context[i], once that context
        has been seen at least `min_context_count` times;
      - otherwise the running global mean, once at least `min_global_count`
        past values exist;
      - otherwise NaN (warm-up).

    This is the universal generalization of the reference implementation's
    seasonal profile. Causality is structural: statistics are updated AFTER
    being read, so position i never sees itself or the future.
    """
    values = np.asarray(values, dtype=float)
    context = np.asarray(context)
    n = len(values)
    if len(context) != n:
        raise ValueError("values and context must have the same length")

    expected = np.zeros(n)
    sums: dict = {}
    counts: dict = {}
    global_sum, global_n = 0.0, 0

    for i in range(n):
        key = context[i] if context.ndim == 1 else tuple(context[i])
        c = counts.get(key, 0)
        if c >= min_context_count:
            expected[i] = sums[key] / c
        elif global_n >= min_global_count:
            expected[i] = global_sum / global_n
        else:
            expected[i] = np.nan
        # update AFTER reading — strict causality by construction
        sums[key] = sums.get(key, 0.0) + values[i]
        counts[key] = c + 1
        global_sum += values[i]
        global_n += 1

    return expected


class CausalConditionalMean:
    """Reusable causal expectation over a categorical context.

    Example with two arbitrary categorical coordinates:

        ctx = np.stack([category_a, category_b], axis=1)
        omega_hat = CausalConditionalMean(min_context_count=10)(omega, ctx)
    """

    def __init__(self, min_context_count: int = 10, min_global_count: int = 720):
        self.min_context_count = min_context_count
        self.min_global_count = min_global_count

    def __call__(self, values: np.ndarray, context: np.ndarray) -> np.ndarray:
        return causal_conditional_mean(
            values,
            context,
            min_context_count=self.min_context_count,
            min_global_count=self.min_global_count,
        )
