"""Access-plane acquisition contracts and adapters."""

from app.acquisition.contracts import AcquisitionAdapter, AcquisitionResult
from app.acquisition.gateway import (
    AcquisitionAdapterError,
    TelegraphGatewayAdapter,
)
from app.acquisition.provider import configured_acquisition_adapter

__all__ = [
    "AcquisitionResult",
    "AcquisitionAdapter",
    "AcquisitionAdapterError",
    "TelegraphGatewayAdapter",
    "configured_acquisition_adapter",
]
