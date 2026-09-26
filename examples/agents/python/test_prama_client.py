"""Pure HTTP transport doubles; no real request or payment."""
import base64
import json
import httpx
import pytest
from prama_client import Policy, PramaClient

ENDPOINT = "https://prama-dynamagh.up.railway.app/v1/public/ask"
MID = "00000000-0000-0000-0000-000000000001"


def fixture(changes=None, paid_status=202):
    requirements = {"scheme": "exact", "network": "eip155:84532", "asset": "asset", "payTo": "recipient",
                    "amount": "10000", "extra": {"name": "USDC", "version": "2"}}
    requirements.update(changes or {})
    challenge = {"x402Version": 2, "resource": {"url": ENDPOINT}, "accepts": [requirements]}
    calls, signatures, checkpoints = [], [], []
    def transport(request):
        calls.append(request)
        if request.method == "GET":
            assert request.headers["X-PRAMA-Result-Capability"] == "test-capability"
            return httpx.Response(200, json={"consumer_result": {"status": "DELIVERED", "results": [{"content": "answer"}]}})
        if "PAYMENT-SIGNATURE" in request.headers:
            return httpx.Response(paid_status, json={"mandate_id": MID, "result_endpoint": ENDPOINT + "/" + MID + "/result",
                                                    "result_capability": "test-capability"})
        return httpx.Response(402, headers={"PAYMENT-REQUIRED": base64.b64encode(json.dumps(challenge).encode()).decode()})
    def signer(challenge):
        signatures.append(challenge)
        return "test-signature"
    client = PramaClient(policy=Policy(network="eip155:84532", asset="asset", recipient="recipient"),
        signer=signer, checkpoint=checkpoints.append, http=httpx.Client(transport=httpx.MockTransport(transport)))
    return client, calls, signatures, checkpoints


def test_one_authorization_same_body_and_private_checkpoint():
    client, calls, signatures, checkpoints = fixture()
    assert client.request("WEB_SEARCH", "  preserve exact query  ")["consumer_result"]["status"] == "DELIVERED"
    assert len(signatures) == 1
    assert len(calls) == 3
    assert calls[0].content == calls[1].content
    assert calls[0].headers["Idempotency-Key"] == calls[1].headers["Idempotency-Key"]
    assert checkpoints[1]["result_capability"] == "test-capability"
    with pytest.raises(RuntimeError):
        client.request("WEB_SEARCH", "second")
    assert len(calls) == 3


@pytest.mark.parametrize("changes", [{"amount": "50001"}, {"amount": "-1"}, {"network": "eip155:8453"},
    {"asset": "other"}, {"payTo": "other"}, {"extra": {}}, {"scheme": "other"}])
def test_bad_terms_never_sign(changes):
    client, calls, signatures, checkpoints = fixture(changes)
    with pytest.raises(ValueError):
        client.request("WEB_SEARCH", "need")
    assert len(calls) == 1 and signatures == [] and checkpoints == []


def test_ambiguous_response_never_retries():
    client, calls, signatures, checkpoints = fixture(paid_status=503)
    with pytest.raises(RuntimeError):
        client.request("WEB_SEARCH", "need")
    assert len(calls) == 2 and len(signatures) == 1
    assert len(checkpoints) == 1
