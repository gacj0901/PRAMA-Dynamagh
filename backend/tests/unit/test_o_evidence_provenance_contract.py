"""Pure conformance checks for O_EVIDENCE_PROVENANCE v0.1."""

import numpy as np

from app.observers.provenance import KERNEL_CONFIG, MIN_CONTEXT_COUNT, MIN_GLOBAL_COUNT, _causal_expected
from app.prama_v030 import KernelV3, causal_conditional_mean


def test_contract_uses_frozen_support_and_certified_kernel_defaults():
    assert MIN_CONTEXT_COUNT == 2
    assert MIN_GLOBAL_COUNT == 2
    assert KERNEL_CONFIG.h == 1.0
    assert KERNEL_CONFIG.tau == 336.0
    assert KERNEL_CONFIG.theta_scale == 2.0
    assert KERNEL_CONFIG.lambda_0 == 1.0
    assert KERNEL_CONFIG.lambda_min == 0.1
    assert KERNEL_CONFIG.lambda_max == 1.0
    assert KERNEL_CONFIG.kappa_v3 == 9.957514604354753e-7
    assert KERNEL_CONFIG.g_smooth == 24
    assert KERNEL_CONFIG.delta_ref == 1.0


def test_causal_expectation_is_strict_and_context_then_global():
    same = ("miner-a", "CRYPTO_PRICE")
    other = ("miner-b", "CRYPTO_PRICE")
    assert _causal_expected([], [], same) is None
    assert _causal_expected([0.0, 1.0], [same, same], same) == 0.5
    assert _causal_expected([0.0, 1.0], [same, other], ("miner-c", "CRYPTO_PRICE")) == 0.5


def test_vendored_kernel_is_bytewise_deterministic_for_same_stream():
    values = [(0.0, 0.5), (1.0, 0.5), (0.0, 0.25)]
    first = KernelV3(KERNEL_CONFIG)
    second = KernelV3(KERNEL_CONFIG)
    first_rows = [first.step(omega, expected, 0.0, None).as_dict() for omega, expected in values]
    second_rows = [second.step(omega, expected, 0.0, None).as_dict() for omega, expected in values]
    assert first_rows == second_rows
    assert np.isfinite(first_rows[-1]["delta"])


def test_certified_causal_reference_excludes_current_value():
    context = np.asarray([["miner-a", "CRYPTO_PRICE"], ["miner-a", "CRYPTO_PRICE"], ["miner-a", "CRYPTO_PRICE"]], dtype=object)
    result_a = causal_conditional_mean(np.asarray([0.0, 1.0, 100.0]), context, 2, 2)
    result_b = causal_conditional_mean(np.asarray([0.0, 1.0, -100.0]), context, 2, 2)
    assert np.isnan(result_a[0]) and np.isnan(result_a[1])
    assert result_a[2] == result_b[2] == 0.5
