"""Discovery projection of the configured Telegraph registry, not E1 coverage.

No paid calls. Expired/failed reads never fall back to an invented intent list.
"""
import json
import os
import re
import time
from threading import Lock
from urllib.request import urlopen

# An upstream listing alone does not resolve a known routing incident.
PUBLIC_INTENT_HOLDS = {"RESEARCH_QUERY": "TELEGRAPH_TEAM_INVESTIGATING"}
_lock = Lock()
_cache = None
TTL_SECONDS = 60


def canonical_public_intents(document):
    if not isinstance(document, dict) or not isinstance(document.get("intents"), list):
        raise ValueError("INVALID_INTENT_REGISTRY")
    rows = document["intents"]
    if document.get("count") != len(rows):
        raise ValueError("INCOMPLETE_INTENT_REGISTRY")
    result = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_INTENT_REGISTRY")
        name = row.get("intent_id")
        count = row.get("miner_count")
        if (row.get("canonical") is True and isinstance(name, str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                and type(count) is int and count > 0
                and row.get("enabled", True) is True
                and row.get("disabled", False) is False
                and row.get("experimental", False) is False
                and row.get("status", "active") in {"active", "enabled", "supported"}
                and name not in PUBLIC_INTENT_HOLDS):
            result.add(name)
    return tuple(sorted(result))


def _fetch_registry(base):
    with urlopen(base + "/intents", timeout=3) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("INTENT_REGISTRY_TOO_LARGE")
    return json.loads(raw)


def public_intents():
    global _cache
    base = os.environ.get("GATEWAY_URL", "").rstrip("/")
    if not base:
        return ()
    with _lock:
        now = time.monotonic()
        if _cache and _cache[0] == base and now < _cache[1]:
            return _cache[2]
        try:
            names = canonical_public_intents(_fetch_registry(base))
        except (OSError, ValueError, TypeError):
            # Short failure cooldown, no stale advertising and no payment impact.
            _cache = (base, now + 5, ())
            return ()
        _cache = (base, time.monotonic() + TTL_SECONDS, names)
        return names
