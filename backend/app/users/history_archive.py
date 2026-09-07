"""Short-lived per-user history export files.

The export is generated from the user's already-authorized database view and
is stored only in the service temporary directory. A timer removes it after
two hours; stale files are also removed opportunistically on the next export.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
from pathlib import Path
from typing import Any

ARCHIVE_TTL_SECONDS = 2 * 60 * 60
ARCHIVE_DIR = Path(tempfile.gettempdir()) / "prama-user-history"


def _path(user_id: str) -> Path:
    safe_id = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return ARCHIVE_DIR / f"{safe_id}.json"


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _expire(path: Path) -> None:
    timer = threading.Timer(ARCHIVE_TTL_SECONDS, _remove, args=(path,))
    timer.daemon = True
    timer.start()


def write_archive(user_id: str, payload: dict[str, Any]) -> Path:
    ARCHIVE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _path(user_id)
    _remove(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    _expire(path)
    return path


def cleanup_expired() -> None:
    if not ARCHIVE_DIR.exists():
        return
    import time

    cutoff = time.time() - ARCHIVE_TTL_SECONDS
    for path in ARCHIVE_DIR.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                _remove(path)
        except OSError:
            continue

