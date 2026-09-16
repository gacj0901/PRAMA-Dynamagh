"""Explicit Access Plane provider selection for the current deployment."""

from typing import Any, Callable
from urllib.request import urlopen

from app.acquisition.contracts import AcquisitionAdapter
from app.acquisition.gateway import TelegraphGatewayAdapter


def configured_acquisition_adapter(
    *,
    timeout_seconds: int,
    urlopen_fn: Callable[..., Any] = urlopen,
) -> AcquisitionAdapter:
    """Return the configured adapter without exposing provider details upstream."""

    return TelegraphGatewayAdapter.from_environment(
        timeout_seconds=timeout_seconds,
        urlopen_fn=urlopen_fn,
    )
