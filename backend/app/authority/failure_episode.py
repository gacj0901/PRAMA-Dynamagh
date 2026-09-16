"""Trusted causal identity for attributable external dependency failures."""

from __future__ import annotations

import hashlib
import json
from typing import Any


FAILURE_EPISODE_SCHEMA_VERSION = "g13-failure-episode-v0.1"
FAILURE_EPISODE_PROVIDER = "TELEGRAPH"
FAILURE_EPISODE_ACCESS_MECHANISM = "GATEWAY"

# Keep this taxonomy aligned with the versioned G13 policy.  The identity is
# created from trusted local lineage, never from provider response metadata.
EXTERNAL_DEPENDENCY_FAILURE_CODES = frozenset({
    "GATEWAY_UNAVAILABLE",
    "TELEGRAPH_UNAVAILABLE",
    "TELEGRAPH_REQUEST_FAILED",
    "X402_FACILITATOR_TIMEOUT",
    "PAYMENT_FAILED",
    "PAYMENT_REQUIRED",
})


def is_external_dependency_failure(code: str | None) -> bool:
    return isinstance(code, str) and code in EXTERNAL_DEPENDENCY_FAILURE_CODES


def _canonical_bytes(material: dict[str, Any]) -> bytes:
    return json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def failure_episode_id(
    *,
    agent_identity_id: str | None,
    mandate_id: str,
    acquisition_id: str,
    causal_request_id: str | None,
    provider: str = FAILURE_EPISODE_PROVIDER,
    access_mechanism: str = FAILURE_EPISODE_ACCESS_MECHANISM,
) -> str:
    """Derive one stable episode identity from trusted request lineage.

    The acquisition task is the stable causal root for retries of one request.
    Provider/access labels remain provenance fields and are not themselves the
    identity.  A new task or request lineage receives a different identity.
    """

    material = {
        "schema_version": FAILURE_EPISODE_SCHEMA_VERSION,
        "agent_identity_id": agent_identity_id,
        "mandate_id": mandate_id,
        "acquisition_id": acquisition_id,
        "causal_request_id": causal_request_id,
        "provider": provider,
        "access_mechanism": access_mechanism,
    }
    digest = hashlib.sha256(_canonical_bytes(material)).hexdigest()
    return f"fep-{digest[:32]}"


def valid_failure_episode_id(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 128 and not any(ch.isspace() for ch in value)


__all__ = [
    "EXTERNAL_DEPENDENCY_FAILURE_CODES",
    "FAILURE_EPISODE_ACCESS_MECHANISM",
    "FAILURE_EPISODE_PROVIDER",
    "FAILURE_EPISODE_SCHEMA_VERSION",
    "failure_episode_id",
    "is_external_dependency_failure",
    "valid_failure_episode_id",
]
