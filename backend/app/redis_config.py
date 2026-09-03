"""Redacted runtime diagnostics for the private Redis connection."""

from __future__ import annotations

import hmac
import os
from urllib.parse import unquote, urlsplit

import redis


def redis_url() -> str:
    # Preserve the exact Railway-provided URL, including its logical database
    # suffix (/3).  No secondary password or URL source may override it.
    return os.environ.get("REDIS_URL", "redis://redis:6379/3")


def redis_runtime_diagnostics() -> dict[str, object]:
    """Return configuration equivalence and PING state without secret values."""
    raw = redis_url()
    parsed = urlsplit(raw)
    expected_user = os.environ.get("PRAMA_REDIS_EXPECTED_USER")
    expected_password = os.environ.get("PRAMA_REDIS_EXPECTED_PASSWORD")
    actual_user = unquote(parsed.username or "")
    actual_password = unquote(parsed.password or "")
    try:
        redis.from_url(raw).ping()
        ping = "READY"
    except redis.AuthenticationError:
        ping = "AUTHENTICATION_ERROR"
    except redis.RedisError:
        ping = "UNAVAILABLE"
    return {
        "source": "REDIS_URL",
        "database": parsed.path or "/0",
        "url_has_username": bool(actual_user),
        "url_has_password": bool(actual_password),
        "expected_user_present": expected_user is not None,
        "expected_password_present": expected_password is not None,
        "username_matches_reference": None if expected_user is None else hmac.compare_digest(actual_user, expected_user),
        "password_matches_reference": None if expected_password is None else hmac.compare_digest(actual_password, expected_password),
        "authenticated_ping": ping,
    }
