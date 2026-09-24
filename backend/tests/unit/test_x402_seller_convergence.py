import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.domain.mandates import InboundX402Payment
from app.api import x402


client = TestClient(app)


def _payment_header() -> str:
    payload = {"payload": {"authorization": {"from": "0x1111111111111111111111111111111111111111"}}}
    return base64.b64encode(json.dumps(payload).encode()).decode()


class _Query:
    def __init__(self, row):
        self.row = row

    def filter_by(self, **_kwargs):
        return self

    def one_or_none(self):
        return self.row


class _Session:
    def __init__(self, state):
        self.state = state
        self.added = []

    def query(self, _model):
        return _Query(self.state.get("payment"))

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    def flush(self):
        for value in self.added:
            if isinstance(value, InboundX402Payment) and not value.payment_id:
                value.payment_id = "payment-1"

    def commit(self):
        for value in self.added:
            if isinstance(value, InboundX402Payment):
                self.state["payment"] = value

    def rollback(self):
        self.added.clear()

    def close(self):
        return None

    def get(self, model, identity):
        row = self.state.get("payment")
        return row if model is InboundX402Payment and row and row.payment_id == identity else None


def _fake_sessions(monkeypatch, state):
    monkeypatch.setattr(x402, "SessionLocal", lambda: _Session(state))


def test_verify_failure_creates_no_work(monkeypatch):
    state = {}
    _fake_sessions(monkeypatch, state)
    calls = []

    def fake_facilitator(operation, *_args):
        calls.append(operation)
        return {"isValid": False, "invalidReason": "INVALID_PAYMENT"}

    monkeypatch.setattr(x402, "_facilitator", fake_facilitator)
    response = client.post(
        "/v1/public/ask",
        headers={"X-PAYMENT": _payment_header()},
        json={"intent": "CRYPTO_PRICE", "request": "price"},
    )

    assert response.status_code == 402
    assert calls == ["verify"]
    assert state == {}


def test_settle_failure_creates_payment_audit_but_no_mandate_or_task(monkeypatch):
    state = {}
    _fake_sessions(monkeypatch, state)
    calls = []

    def fake_facilitator(operation, *_args):
        calls.append(operation)
        return {"isValid": True} if operation == "verify" else {"success": False, "errorReason": "DECLINED"}

    monkeypatch.setattr(x402, "_facilitator", fake_facilitator)
    response = client.post(
        "/v1/public/ask",
        headers={"X-PAYMENT": _payment_header(), "Idempotency-Key": "settle-failure"},
        json={"intent": "CRYPTO_PRICE", "request": "price"},
    )

    assert response.status_code == 402
    assert calls == ["verify", "settle"]
    assert state["payment"].payment_status == "FAILED_SETTLE"
    assert not any(getattr(value, "mandate_id", None) for value in (state["payment"],))


def test_happy_path_settles_before_mandate_and_dispatch(monkeypatch):
    state = {}
    _fake_sessions(monkeypatch, state)
    calls = []

    def fake_facilitator(operation, *_args):
        calls.append(operation)
        return {"isValid": True} if operation == "verify" else {"success": True, "txHash": "0xabc"}

    dispatched = []
    monkeypatch.setattr(x402, "_facilitator", fake_facilitator)
    seen = {}

    def fake_create_settled(*_args, **kwargs):
        seen["external_agent_id"] = kwargs["external_agent_id"]
        return SimpleNamespace(mandate_id="mandate-1"), SimpleNamespace(acquisition_id="task-1")

    monkeypatch.setattr(
        x402,
        "_create_settled_mandate",
        fake_create_settled,
    )
    monkeypatch.setattr(x402, "execute_acquisition", SimpleNamespace(delay=lambda *args: dispatched.append(args)))
    response = client.post(
        "/v1/public/ask",
        headers={"X-PAYMENT": _payment_header(), "Idempotency-Key": "happy-path"},
        json={"intent": "CRYPTO_PRICE", "request": "price"},
    )

    assert response.status_code == 202
    assert calls == ["verify", "settle"]
    assert state["payment"].payment_status == "SETTLED"
    assert dispatched == [("mandate-1", "task-1")]
    assert seen["external_agent_id"] is None


def test_same_idempotency_replays_without_facilitator_or_second_settlement(monkeypatch):
    intent, query = "CRYPTO_PRICE", "price"
    fingerprint = x402._request_fingerprint(intent, query)
    row = InboundX402Payment(
        payment_id="payment-1",
        request_id="request-1",
        mandate_id="mandate-1",
        payer_wallet_address="0x1111111111111111111111111111111111111111",
        recipient_wallet_address=x402.X402_RECIPIENT,
        network=x402.X402_NETWORK,
        asset=x402.X402_ASSET,
        amount_usdc=x402.X402_AMOUNT_USDC,
        facilitator=x402.X402_FACILITATOR,
        payment_status="SETTLED",
        settlement_reference=json.dumps({"request_hash": fingerprint}),
        idempotency_key="same-request",
    )
    state = {"payment": row}
    _fake_sessions(monkeypatch, state)
    monkeypatch.setattr(x402, "_facilitator", lambda *_args: (_ for _ in ()).throw(AssertionError("facilitator called")))

    response = client.post(
        "/v1/public/ask",
        headers={"X-PAYMENT": _payment_header(), "Idempotency-Key": "same-request"},
        json={"intent": intent, "request": query},
    )
    assert response.status_code == 202


def test_conflicting_payload_rejected_before_facilitator(monkeypatch):
    row = InboundX402Payment(
        payment_id="payment-1",
        request_id="request-1",
        mandate_id="mandate-1",
        payer_wallet_address="0x1111111111111111111111111111111111111111",
        recipient_wallet_address=x402.X402_RECIPIENT,
        network=x402.X402_NETWORK,
        asset=x402.X402_ASSET,
        amount_usdc=x402.X402_AMOUNT_USDC,
        facilitator=x402.X402_FACILITATOR,
        payment_status="SETTLED",
        settlement_reference=json.dumps({"request_hash": x402._request_fingerprint("CRYPTO_PRICE", "old")}),
        idempotency_key="conflict",
    )
    state = {"payment": row}
    _fake_sessions(monkeypatch, state)
    monkeypatch.setattr(x402, "_facilitator", lambda *_args: (_ for _ in ()).throw(AssertionError("facilitator called")))

    response = client.post(
        "/v1/public/ask",
        headers={"X-PAYMENT": _payment_header(), "Idempotency-Key": "conflict"},
        json={"intent": "CRYPTO_PRICE", "request": "new"},
    )
    assert response.status_code == 409
