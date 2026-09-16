"""Explicit Access Plane provider selection for the current deployment."""

import os
from typing import Any, Callable
from urllib.request import urlopen

from app.acquisition.contracts import AcquisitionAdapter
from app.acquisition.gateway import TelegraphGatewayAdapter
from app.acquisition.mcp import TelegraphMCPAdapter


def configured_acquisition_adapter(
    *,
    timeout_seconds: int,
    urlopen_fn: Callable[..., Any] = urlopen,
) -> AcquisitionAdapter:
    """Return the configured adapter without exposing provider details upstream."""

    provider = os.environ.get("ACQUISITION_PROVIDER", "GATEWAY").strip().upper()
    if provider == "GATEWAY":
        return TelegraphGatewayAdapter.from_environment(
            timeout_seconds=timeout_seconds,
            urlopen_fn=urlopen_fn,
        )
    if provider == "MCP":
        # Explicit selection is fail-closed; MCP never silently falls back to HTTP.
        return TelegraphMCPAdapter.from_environment(timeout_seconds=timeout_seconds)
    raise ValueError(f"Unsupported ACQUISITION_PROVIDER: {provider}")
