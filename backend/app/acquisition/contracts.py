"""Provider-neutral contracts for the Access Plane.

The authority and evidence layers consume only the normalized fields below.
``raw_payload`` is retained for provenance and replay, but is intentionally
opaque to those layers.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    """Normalized output produced by an acquisition adapter."""

    provider: str
    miner_id: str | None
    miner_name: str | None
    intent: str | None
    signal_hash: str | None
    cost_usdc: Decimal | None
    duration_ms: int | None
    reasoning: str | None
    warnings: list[Any] = field(default_factory=list)
    raw_payload: Any = None
    http_status: int | None = None
    # Provenance distinguishes the intelligence source from the access path.
    access_mechanism: str = "UNKNOWN"


class AcquisitionAdapter(Protocol):
    """Provider-neutral Access Plane interface consumed by the worker."""

    provider: str

    def acquire(
        self,
        *,
        query: str,
        requested_intent: str | None,
        causal_request_id: str,
        budget_usdc: Decimal,
    ) -> AcquisitionResult:
        ...
