"""Contract tests for the Gateway Access Plane adapter."""

import io
import json
from decimal import Decimal
from urllib.error import HTTPError, URLError

import pytest

from app.acquisition.gateway import AcquisitionAdapterError, TelegraphGatewayAdapter


class _Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self):
        return json.dumps(self.body).encode()


def test_gateway_adapter_normalizes_provider_response_without_exposing_transport():
    captured = {}

    def transport(request, **kwargs):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = kwargs["timeout"]
        return _Response(
            {
                "miner_id": "miner-1",
                "miner_name": "Miner One",
                "intent": "CRYPTO_PRICE",
                "signal_hash": "0xsignal",
                "payment": {"amount_usdc": "0.006000"},
                "duration_ms": 42,
                "reasoning": "reason",
                "warnings": ["warning"],
                "result": {"opaque": True},
            }
        )

    result = TelegraphGatewayAdapter(
        base_url="http://gateway.test/",
        timeout_seconds=17,
        internal_token="secret",
        urlopen_fn=transport,
    ).acquire(
        query="price",
        requested_intent="CRYPTO_PRICE",
        causal_request_id="mandate-1",
        budget_usdc=Decimal("0.010000"),
    )

    assert captured == {
        "url": "http://gateway.test/ask",
        "payload": {
            "query": "price",
            "context": {"requested_intent": "CRYPTO_PRICE"},
            "causal_request_id": "mandate-1",
            "budget_usdc": "0.010000",
        },
        "timeout": 17,
    }
    assert result.provider == "TELEGRAPH"
    assert result.miner_id == "miner-1"
    assert result.cost_usdc == Decimal("0.006000")
    assert result.raw_payload["result"] == {"opaque": True}


def test_gateway_adapter_preserves_http_error_code_and_status():
    def transport(*args, **kwargs):
        raise HTTPError(
            url="http://gateway.test/ask",
            code=402,
            msg="Payment Required",
            hdrs=None,
            fp=io.BytesIO(b'{"code":"PAYMENT_REQUIRED"}'),
        )

    with pytest.raises(AcquisitionAdapterError) as raised:
        TelegraphGatewayAdapter(base_url="http://gateway.test", urlopen_fn=transport).acquire(
            query="price",
            requested_intent=None,
            causal_request_id="m",
            budget_usdc=Decimal("0.010000"),
        )
    assert raised.value.code == "PAYMENT_REQUIRED"
    assert raised.value.http_status == 402


def test_gateway_adapter_classifies_transport_failure():
    def transport(*args, **kwargs):
        raise URLError("connection refused")

    with pytest.raises(AcquisitionAdapterError) as raised:
        TelegraphGatewayAdapter(base_url="http://gateway.test", urlopen_fn=transport).acquire(
            query="price",
            requested_intent=None,
            causal_request_id="m",
            budget_usdc=Decimal("0.010000"),
        )
    assert raised.value.code == "GATEWAY_UNAVAILABLE"
