"""Access-plane acquisition contracts and adapters."""

from app.acquisition.contracts import (
    AcquisitionAdapter,
    AcquisitionRequest,
    AcquisitionResult,
    ResourceAdapter,
    X402_PAYMENT_RAIL,
)
from app.acquisition.gateway import (
    AcquisitionAdapterError,
    TelegraphGatewayAdapter,
)
from app.acquisition.mcp import MCPPreflight, MCPProtocolError, TelegraphMCPAdapter
from app.acquisition.provider import configured_acquisition_adapter

__all__ = [
    "AcquisitionResult",
    "AcquisitionRequest",
    "AcquisitionAdapter",
    "ResourceAdapter",
    "X402_PAYMENT_RAIL",
    "AcquisitionAdapterError",
    "TelegraphGatewayAdapter",
    "TelegraphMCPAdapter",
    "MCPProtocolError",
    "MCPPreflight",
    "configured_acquisition_adapter",
]
