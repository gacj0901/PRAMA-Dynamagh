"""Run pytest without outbound sockets; Windows asyncio self-pipes are allowed.

Usage (from backend): python tests/offline_runner.py -q tests/unit/...
No application services or external databases are contacted.
"""
import os
import socket
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_connect = socket.socket.connect


def offline_connect(self, address):
    caller = sys._getframe(1)
    if (caller.f_code.co_name == "_fallback_socketpair"
            and caller.f_code.co_filename == socket.__file__):
        return _connect(self, address)
    raise RuntimeError("NETWORK_DISABLED_FOR_TESTS")


def denied(*args, **kwargs):
    raise RuntimeError("NETWORK_DISABLED_FOR_TESTS")


socket.socket.connect = offline_connect
socket.socket.connect_ex = denied
socket.getaddrinfo = denied

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main(["-p", "no:cacheprovider", *sys.argv[1:]]))
