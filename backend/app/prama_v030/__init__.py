"""Vendored, byte-preserving PRAMA Protokol v0.3.0 execution surface.

The implementation files in this package are copied from the certified
PRAMA-Protokol v0.3.0 Python reference. They are not reimplemented here.
"""

from .interface import CausalConditionalMean, ObservationInterface, causal_conditional_mean
from .kernel_v3 import (
    GammaRowV3,
    GammaV3,
    KernelConfigV3,
    KernelV3,
    NumericAuditV3,
    V3ProjectionError,
    project_v3,
)

__version__ = "0.3.0"

__all__ = [
    "CausalConditionalMean",
    "ObservationInterface",
    "causal_conditional_mean",
    "GammaRowV3",
    "GammaV3",
    "KernelConfigV3",
    "KernelV3",
    "NumericAuditV3",
    "V3ProjectionError",
    "project_v3",
]
