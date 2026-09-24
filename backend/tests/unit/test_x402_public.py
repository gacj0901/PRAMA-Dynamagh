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
    assert body["x402Version"] == 2
    assert body["method"] == "POST"
    assert body["url"].endswith("/v1/public/ask")
    requirement = body["accepts"][0]
    assert requirement["scheme"] == "exact"
    assert requirement["network"]
    assert requirement["asset"].startswith("0x")
    assert requirement["payTo"].startswith("0x")
    assert requirement["amount"] == "10000"


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
