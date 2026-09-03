from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.main import app
from app import public_safety
from app.redis_config import redis_url


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds


def request(ip: str = "198.51.100.8") -> Request:
    return Request({"type": "http", "headers": [(b"x-real-ip", ip.encode())], "client": (ip, 5000)})


def test_public_budget_hard_cap(monkeypatch):
    monkeypatch.setenv("PUBLIC_MAX_MANDATE_USDC", "0.010000")
    public_safety.enforce_public_budget(Decimal("0.010000"))
    with pytest.raises(HTTPException) as raised:
        public_safety.enforce_public_budget(Decimal("0.010001"))
    assert raised.value.status_code == 422
    assert raised.value.detail == "PUBLIC_MANDATE_BUDGET_EXCEEDED"


def test_public_rate_limit_and_redis_fail_closed(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setenv("PUBLIC_MANDATE_RATE_LIMIT", "2")
    monkeypatch.setenv("PUBLIC_MANDATE_RATE_WINDOW_SECONDS", "600")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid/3")
    monkeypatch.setattr(public_safety.redis, "from_url", lambda _: fake)
    public_safety.enforce_public_rate_limit(request())
    public_safety.enforce_public_rate_limit(request())
    with pytest.raises(HTTPException) as limited:
        public_safety.enforce_public_rate_limit(request())
    assert limited.value.status_code == 429
    assert fake.expirations and next(iter(fake.expirations.values())) == 600
    monkeypatch.setattr(public_safety.redis, "from_url", lambda _: (_ for _ in ()).throw(public_safety.redis.ConnectionError()))
    with pytest.raises(HTTPException) as unavailable:
        public_safety.enforce_public_rate_limit(request("198.51.100.9"))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == "PUBLIC_RATE_LIMIT_UNAVAILABLE"


def test_redis_url_preserves_the_provider_database_index(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://default:secret@redis.railway.internal:6379/3")
    assert redis_url().endswith("/3")


def test_public_onchain_write_routes_are_hidden_and_rejected():
    client = TestClient(app)
    assert client.post("/v1/erc8183/jobs").status_code == 404
    assert client.post("/v1/erc8183/jobs/not-a-job/cancel").status_code == 404
    assert client.post("/v1/tickets/not-a-ticket/anchor").status_code == 404
