import base64
import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _decode_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode())


def test_x402_manifest_is_public_json_and_points_to_post_seller():
    response = client.get("/.well-known/x402-service.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["x402"] == "1.0"
    assert body["capabilities"] == ["evidence_bound_intelligence_acquisition"]
    assert body["pricing"] == {"currency": "USDC", "base": "0.010000", "unit": "request"}
    assert body["payment"]["address"].startswith("0x")
    assert body["payment"]["chain"] == "base-sepolia"
    assert body["payment"]["facilitator"]
    assert body["endpoint"].endswith("/v1/public/ask")


def test_x402_seller_returns_payment_challenge_without_payment():
    response = client.post(
        "/v1/public/ask",
        json={"intent": "CRYPTO_PRICE", "request": "What is the current price of ETH in USD?"},
    )

    assert response.status_code == 402
    assert response.headers["content-type"].startswith("application/json")
    assert "payment-required" in response.headers
    body = response.json()
    assert body["x402Version"] == 2
    encoded = _decode_header(response.headers["payment-required"])
    assert encoded["x402Version"] == 2
    assert encoded["accepts"][0]["resource"].endswith("/v1/public/ask")
