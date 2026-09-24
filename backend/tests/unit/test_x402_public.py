import base64
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_sqlite(type_, compiler, **kw):  # noqa: ANN001
    """Render Postgres JSONB columns as plain JSON when targeting SQLite.

    Tests use an in-memory SQLite database; production runs Postgres and the
    real JSONB type is unaffected.  This compile-only shim is scoped to the
    pytest process and never touches production code.
    """
    return "JSON"

from app.domain.mandates import (
    AcquisitionTask,
    Base,
    InboundX402Payment,
    Mandate,
)
from app.main import app
from app.persistence.database import get_session

client = TestClient(app)


def _decode_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode())


def test_x402_manifest_is_public_json_and_points_to_post_seller():
    response = client.get("/.well-known/x402-service.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["x402"] == "1.0"
    assert set(body) == {"x402", "name", "description", "capabilities", "pricing", "payment", "endpoint"}
    assert body["capabilities"] == [
        "evidence_bound_intelligence_acquisition",
        "principle:paid_miner_output_is_not_authorization",
        "epistemic_coverage:framework=E1/E2;e1_targets=[CRYPTO_PRICE]",
    ]
    assert "paid_miner_output_is_not_authorization" in body["description"]
    assert "framework=E1/E2" in body["description"]
    assert 'e1_targets=["CRYPTO_PRICE"]' in body["description"]
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
    assert encoded["accepts"][0]["network"] == "eip155:84532"
    assert len(encoded["accepts"][0]["asset"]) == 42
    assert encoded["accepts"][0]["amount"] == "10000"


# ---------------------------------------------------------------------------
# Behavioral suite: sessions, facilitator doubles, lineage assertions.
#
# Design constraints (per operator):
#   * Production code is unchanged.  No runtime mock flag is introduced.
#   * Tests substitute the facilitator HTTP call (`_facilitator`) via
#     monkeypatch — the double lives ONLY inside the pytest process.
#   * Per-test SQLite files keep each test self-contained and allow a fresh
#     engine to verify persistence across a simulated application restart.
#   * No network.  No real USDC.  No real settlement.
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    import sqlite3
    import tempfile
    from decimal import Decimal
    from pathlib import Path

    # sqlite3 does not bind Decimal natively; PostgreSQL NUMERIC does. Keep
    # the test-only adapter exact by binding the canonical decimal string.
    sqlite3.register_adapter(Decimal, str)

    from sqlalchemy.engine import URL

    temporary_directory = tempfile.TemporaryDirectory(
        dir=Path(__file__).resolve().parents[2], prefix=".x402-test-"
    )
    database_path = Path(temporary_directory.name) / "x402-test.sqlite3"

    engine = create_engine(
        URL.create("sqlite", database=str(database_path)),
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _register_sqlite_test_functions(dbapi_connection, _connection_record):
        dbapi_connection.create_function(
            "NOW",
            0,
            lambda: datetime.now(timezone.utc).isoformat(sep=" "),
        )

    # Create only the tables touched by the x402 path.  Pulling
    # Base.metadata.create_all(engine) trips on Postgres-specific columns
    # (JSONB in structural_evaluations, etc.) which SQLite cannot render.
    # Listing just the relevant tables is deliberate and stable: if any of
    # them adds a Postgres-only column, the failure is loud and localised.
    from app.agents.identity import AgentIdentity  # noqa: F401 — imported for table registry
    from app.domain.mandates import (
        AcquisitionTask,
        InboundX402Payment,
        Mandate,
        MandateTransition,
        PublicManualSpendLedger,
        PublicManualSpendReservation,
        Decision,
        Evidence,
        StructuralEvaluation,
        Ticket,
        UsageEvent,
    )

    for table in (
        AgentIdentity.__table__,
        Mandate.__table__,
        AcquisitionTask.__table__,
        MandateTransition.__table__,
        UsageEvent.__table__,
        InboundX402Payment.__table__,
        PublicManualSpendLedger.__table__,
        PublicManualSpendReservation.__table__,
        Evidence.__table__,
        StructuralEvaluation.__table__,
        Decision.__table__,
        Ticket.__table__,
    ):
        table.create(engine, checkfirst=True)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def _override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    # The canonical endpoint uses SessionLocal() directly, not Depends.
    # Patch the SessionLocal symbol inside app.api.x402 so the router opens
    # a session against an isolated, persistent SQLite file instead of Postgres.
    import app.api.x402 as x402_module
    original = x402_module.SessionLocal
    original_dependency_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = _override
    x402_module.SessionLocal = SessionLocal
    test_session = SessionLocal()
    try:
        yield test_session
    finally:
        test_session.close()
        x402_module.SessionLocal = original
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_dependency_overrides)
        engine.dispose()
        temporary_directory.cleanup()


@pytest.fixture
def facilitator_stub(monkeypatch):
    """Return a controllable facilitator double.

    The stub supports three response shapes:
        ok_verify/ok_settle — happy path
        bad_verify — facilitator says isValid=False
        bad_settle — verify ok, settle returns success=False

    Tests pick via closure parameters.  No network, no real payment.
    """

    import app.api.x402 as x402_module

    class _Stub:
        def __init__(self):
            self.verify_behavior = {"isValid": True}
            self.settle_behavior = {"success": True, "transaction": f"0x{uuid.uuid4().hex}"}
            self.verify_calls = 0
            self.settle_calls = 0

        def __call__(self, operation: str, payload: dict, requirements: dict) -> dict:
            if operation == "verify":
                self.verify_calls += 1
                return dict(self.verify_behavior)
            if operation == "settle":
                self.settle_calls += 1
                return dict(self.settle_behavior)
            raise AssertionError(f"unknown facilitator op: {operation}")

    stub = _Stub()
    monkeypatch.setattr(x402_module, "_facilitator", stub)
    return stub


def _valid_payment_header(payer: str = "0xABCD1234ABCD1234ABCD1234ABCD1234ABCD1234") -> str:
    """Construct a syntactically valid x402 payment header.

    The payload does NOT need a real signature — the facilitator stub
    always returns success.  The router only decodes + extracts payer.
    """
    import app.api.x402 as x402_module

    payload = {
        "x402Version": 2,
        "resource": "https://prama-dynamagh.up.railway.app/v1/public/ask",
        "accepted": {
            "scheme": "exact",
            "network": x402_module.X402_NETWORK,
            "asset": x402_module.X402_ASSET,
            "amount": x402_module.X402_AMOUNT_ATOMIC,
            "payTo": x402_module.X402_RECIPIENT,
            "maxTimeoutSeconds": 300,
        },
        "payload": {
            "signature": "0xfake",
            "authorization": {"from": payer, "to": "0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6", "value": "10000"},
        },
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def _no_worker_execute(monkeypatch):
    """Block execute_acquisition.delay from actually firing Celery."""
    import app.workers.tasks as wt

    class _NoDelay:
        @staticmethod
        def delay(*_args, **_kwargs):
            return None

    monkeypatch.setattr(wt, "execute_acquisition", _NoDelay)

    # The x402 module already imported it at module-load time; patch there too.
    import app.api.x402 as x402_module
    monkeypatch.setattr(x402_module, "execute_acquisition", _NoDelay)


# ---------------------------------------------------------------------------
# 3. verify failure → 0 Mandates / 0 AcquisitionTasks (fail-closed)
# ---------------------------------------------------------------------------


def test_x402_verify_failure_creates_zero_mandates_and_zero_tasks(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)
    facilitator_stub.verify_behavior = {"isValid": False, "invalidReason": "X402_VERIFY_FAILED"}

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"test-verify-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "What is ETH price?"},
    )

    # Canonical contract: verify failure → 402 challenge with error code.
    assert response.status_code == 402

    # Fail-closed: ZERO Mandates, ZERO AcquisitionTasks, ZERO settled payments.
    assert db_session.query(Mandate).count() == 0
    assert db_session.query(AcquisitionTask).count() == 0
    settled = db_session.query(InboundX402Payment).filter_by(payment_status="SETTLED").count()
    assert settled == 0


# ---------------------------------------------------------------------------
# 4. settle failure → 0 Mandates / 0 AcquisitionTasks (fail-closed)
# ---------------------------------------------------------------------------


def test_x402_settle_failure_creates_zero_mandates_and_zero_tasks(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)
    facilitator_stub.verify_behavior = {"isValid": True}
    facilitator_stub.settle_behavior = {"success": False, "errorReason": "insufficient_funds"}

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"test-settle-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )

    assert response.status_code == 402

    # Fail-closed: the row exists with FAILED_SETTLE, but ZERO Mandates / Tasks.
    assert db_session.query(Mandate).count() == 0
    assert db_session.query(AcquisitionTask).count() == 0
    row = db_session.query(InboundX402Payment).first()
    assert row is not None
    assert row.payment_status == "FAILED_SETTLE"


# ---------------------------------------------------------------------------
# 5. happy path — verify ok + settle ok → full lineage persists
# ---------------------------------------------------------------------------


def test_x402_happy_path_persists_full_lineage(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(payer="0xAaaa000000000000000000000000000000000001"),
            "idempotency-key": f"test-happy-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "What is ETH price?"},
    )

    assert response.status_code == 202, f"body={response.json()}"
    body = response.json()
    assert body["status"] == "RECEIVED"
    assert "mandate_id" in body
    assert "request_id" in body
    assert body["result_endpoint"].endswith(f"/v1/public/ask/{body['mandate_id']}/result")
    assert body["status_url"] == body["result_endpoint"]
    assert body["result_capability"]
    assert body["result_capability_header"] == "X-PRAMA-Result-Capability"
    assert "/v1/m2m/" not in body["result_endpoint"]

    # InboundX402Payment persisted with full lineage fields.
    payment = db_session.query(InboundX402Payment).filter_by(request_id=body["request_id"]).one()
    assert payment.payment_status == "SETTLED"
    assert payment.mandate_id == body["mandate_id"]
    assert payment.payer_wallet_address.lower() == "0xaaaa000000000000000000000000000000000001"
    assert payment.amount_usdc == payment.amount_usdc  # smoke: column exists
    assert len(payment.asset) == 42
    assert payment.result_capability_hash == __import__("hashlib").sha256(
        body["result_capability"].encode()
    ).hexdigest()

    # Mandate has origin=M2M per constraint 5.
    mandate = db_session.query(Mandate).filter_by(mandate_id=body["mandate_id"]).one()
    assert mandate.origin == "M2M"
    assert mandate.actor_id == "x402-public"

    # AcquisitionTask exists, queued to Telegraph via Gateway (per 5 & 12).
    task = db_session.query(AcquisitionTask).filter_by(mandate_id=mandate.mandate_id).one()
    assert task.resource_provider == "TELEGRAPH"
    assert task.access_mechanism == "GATEWAY"
    assert task.payment_rail == "X402"


# ---------------------------------------------------------------------------
# 6. same-request idempotency → NO second settlement, NO second mandate
# ---------------------------------------------------------------------------


def test_x402_same_idempotency_key_same_payload_replays_without_second_settlement(
    db_session, facilitator_stub, monkeypatch
):
    _no_worker_execute(monkeypatch)
    idem = f"test-idem-{uuid.uuid4().hex[:12]}"
    headers = {
        "payment-signature": _valid_payment_header(),
        "idempotency-key": idem,
    }
    body = {"intent": "CRYPTO_PRICE", "request": "What is ETH price?"}

    r1 = client.post("/v1/public/ask", headers=headers, json=body)
    assert r1.status_code == 202
    assert facilitator_stub.settle_calls == 1

    r2 = client.post("/v1/public/ask", headers=headers, json=body)
    assert r2.status_code == 202
    body2 = r2.json()
    assert body2["request_id"] == r1.json()["request_id"]
    assert body2["mandate_id"] == r1.json()["mandate_id"]
    assert body2["result_capability"] is None
    assert body2["result_capability_replay"] is True

    # The replay hit the cached SETTLED row — facilitator is NOT called again.
    assert facilitator_stub.settle_calls == 1

    # And: no second mandate was created.
    assert db_session.query(Mandate).count() == 1
    assert db_session.query(AcquisitionTask).count() == 1
    assert db_session.query(InboundX402Payment).count() == 1


# ---------------------------------------------------------------------------
# 7. conflicting-payload idempotency → 409, zero additional settlement
# ---------------------------------------------------------------------------


def test_x402_same_idempotency_key_different_payload_conflicts(
    db_session, facilitator_stub, monkeypatch
):
    _no_worker_execute(monkeypatch)
    idem = f"test-ikc-{uuid.uuid4().hex[:12]}"
    headers = {
        "payment-signature": _valid_payment_header(),
        "idempotency-key": idem,
    }

    r1 = client.post(
        "/v1/public/ask", headers=headers, json={"intent": "CRYPTO_PRICE", "request": "q1"}
    )
    assert r1.status_code == 202
    assert facilitator_stub.settle_calls == 1

    # Same idempotency key, different payload → explicit conflict.
    r2 = client.post(
        "/v1/public/ask", headers=headers, json={"intent": "CRYPTO_PRICE", "request": "q2-DIFFERENT"}
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == "X402_IDEMPOTENCY_KEY_REUSED"

    # No additional settlement occurred; no additional mandate created.
    assert facilitator_stub.settle_calls == 1
    assert db_session.query(Mandate).count() == 1
    assert db_session.query(InboundX402Payment).count() == 1


# ---------------------------------------------------------------------------
# 8. X-Agent-Id present → identity threaded through get_or_create_m2m_identity
# ---------------------------------------------------------------------------


def test_x402_agent_id_present_uses_explicit_identity(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"test-xaid-{uuid.uuid4().hex[:12]}",
            "X-Agent-Id": "agent-alpha-7",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )
    assert response.status_code == 202
    mandate = db_session.query(Mandate).filter_by(mandate_id=response.json()["mandate_id"]).one()
    assert mandate.agent_id == "agent-alpha-7"
    # constraints bag preserves the principal (payment-derived, not identity-derived)
    assert mandate.constraints["source_principal"] == "X402_PUBLIC"
    assert mandate.constraints["external_agent_id"] == "agent-alpha-7"


# ---------------------------------------------------------------------------
# 9. X-Agent-Id absent → external_agent_id NULL, NOT derived from wallet
# ---------------------------------------------------------------------------


def test_x402_no_agent_id_leaves_external_agent_id_null(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(payer="0xDEAD000000000000000000000000000000000002"),
            "idempotency-key": f"test-noaid-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )
    assert response.status_code == 202
    mandate = db_session.query(Mandate).filter_by(mandate_id=response.json()["mandate_id"]).one()
    # Per constraint 7: external_agent_id must NOT be derived from the wallet.
    # The constraints bag serializes None → JSON null (or absence); both OK.
    assert mandate.agent_id is None
    assert mandate.constraints.get("external_agent_id") is None
    # And the wallet principal lives separately, NOT as identity.
    assert mandate.constraints.get("payer_wallet", "").lower() == (
        "0xdead000000000000000000000000000000000002".lower()
    )


# ---------------------------------------------------------------------------
# 10. payer wallet ≠ agent identity (structural separation of economic
#     principal from identity)
# ---------------------------------------------------------------------------


def test_x402_payer_wallet_does_not_create_identity_record(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(payer="0xCAFE00000000000000000000000000000000000b"),
            "idempotency-key": f"test-payer-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )
    assert response.status_code == 202
    payment = db_session.query(InboundX402Payment).filter_by(
        request_id=response.json()["request_id"]
    ).one()

    # Payer wallet is the economic principal — recorded in Leg 1 table ...
    assert payment.payer_wallet_address.lower() == "0xcafe00000000000000000000000000000000000b"
    # ... but NEVER coerced into the Mandate identity. agent_id is NULL here
    # because X-Agent-Id was absent.
    mandate = db_session.query(Mandate).filter_by(mandate_id=payment.mandate_id).one()
    assert mandate.agent_id is None
    assert mandate.agent_identity_id is None


# ---------------------------------------------------------------------------
# 11. Leg 1 / Leg 2 separation — settle record proves the rail is leg-1 only
# ---------------------------------------------------------------------------


def test_x402_leg1_record_does_not_touch_leg2_economics(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"test-legs-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )
    assert response.status_code == 202
    mandate = db_session.query(Mandate).filter_by(mandate_id=response.json()["mandate_id"]).one()

    # Leg 1 fact: source_principal=X402_PUBLIC labels this as inbound-pay.
    assert mandate.constraints.get("source_principal") == "X402_PUBLIC"
    # Leg 2 separation: reserve_m2m_spend went through public_safety (NOT the
    # outbound gateway).  We verify absence of cross-leg contamination by
    # confirming no gateway-side economics are synthesized here.
    assert "telegraph_call_id" not in mandate.constraints
    assert "merchant_wallet" not in mandate.constraints
    # Access mechanism stays explicitly the existing outbound gateway.
    task = db_session.query(AcquisitionTask).filter_by(mandate_id=mandate.mandate_id).one()
    assert task.access_mechanism == "GATEWAY"


# ---------------------------------------------------------------------------
# 12. persisted lineage: InboundX402Payment → Mandate(origin=M2M) → Task
# ---------------------------------------------------------------------------


def test_x402_persisted_lineage_traversal(db_session, facilitator_stub, monkeypatch):
    _no_worker_execute(monkeypatch)

    response = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"test-lineage-{uuid.uuid4().hex[:12]}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "ETH price?"},
    )
    assert response.status_code == 202
    payment = db_session.query(InboundX402Payment).filter_by(
        request_id=response.json()["request_id"]
    ).one()
    assert payment.mandate_id is not None

    # Payment → Mandate
    mandate = db_session.query(Mandate).filter_by(mandate_id=payment.mandate_id).one()
    assert mandate.origin == "M2M"
    assert mandate.actor_id == "x402-public"
    assert mandate.constraints.get("payment_rail") == "X402"

    # Mandate → AcquisitionTask
    task = db_session.query(AcquisitionTask).filter_by(mandate_id=mandate.mandate_id).one()
    assert task.status == "QUEUED"
    assert task.resource_provider == "TELEGRAPH"
    assert task.payment_rail == "X402"

    # setIds match — payment.mandate_id == task.mandate_id (single lineage)
    assert payment.mandate_id == task.mandate_id == mandate.mandate_id
    # Facilitator was called exactly twice (one verify + one settle)
    assert facilitator_stub.verify_calls == 1
    assert facilitator_stub.settle_calls == 1


def test_x402_result_capability_is_mandate_scoped_and_not_global_bearer(
    db_session, facilitator_stub, monkeypatch, caplog
):
    import hashlib

    _no_worker_execute(monkeypatch)
    global_bearer = "test-only-global-m2m-bearer-that-must-not-be-returned"
    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", global_bearer)

    def paid_request(idem: str):
        return client.post(
            "/v1/public/ask",
            headers={
                "payment-signature": _valid_payment_header(),
                "idempotency-key": idem,
            },
            json={"intent": "CRYPTO_PRICE", "request": "BTC price?"},
        )

    first = paid_request(f"scope-a-{uuid.uuid4().hex}")
    second = paid_request(f"scope-b-{uuid.uuid4().hex}")
    assert first.status_code == second.status_code == 202
    a, b = first.json(), second.json()
    assert a["mandate_id"] != b["mandate_id"]
    assert global_bearer not in first.text
    assert a["result_capability"] not in caplog.text

    row = db_session.query(InboundX402Payment).filter_by(mandate_id=a["mandate_id"]).one()
    assert row.result_capability_hash == hashlib.sha256(a["result_capability"].encode()).hexdigest()
    assert row.result_capability_hash != a["result_capability"]

    endpoint_a = a["result_endpoint"]
    endpoint_b = b["result_endpoint"]
    assert client.get(endpoint_a).status_code == 404
    assert client.get(endpoint_a, headers={"X-PRAMA-Result-Capability": "incorrect"}).status_code == 404
    assert client.get(endpoint_a, headers={"Authorization": f"Bearer {global_bearer}"}).status_code == 404
    assert client.get(
        endpoint_b, headers={"X-PRAMA-Result-Capability": a["result_capability"]}
    ).status_code == 404

    recovered = client.get(
        endpoint_a, headers={"X-PRAMA-Result-Capability": a["result_capability"]}
    )
    assert recovered.status_code == 200
    result = recovered.json()
    assert result["mandate_id"] == a["mandate_id"]
    assert result["request_id"] == a["request_id"]
    assert result["origin"] == "M2M"
    assert result["acquisitions"][0]["requested_intent"] == "CRYPTO_PRICE"
    assert "result_capability" not in recovered.text
    assert global_bearer not in recovered.text
    assert recovered.headers["cache-control"] == "no-store"


def test_x402_result_capability_survives_fresh_engine_restart(
    db_session, facilitator_stub, monkeypatch
):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import sessionmaker

    import app.api.x402 as x402_module

    _no_worker_execute(monkeypatch)
    paid = client.post(
        "/v1/public/ask",
        headers={
            "payment-signature": _valid_payment_header(),
            "idempotency-key": f"restart-{uuid.uuid4().hex}",
        },
        json={"intent": "CRYPTO_PRICE", "request": "BTC price?"},
    )
    assert paid.status_code == 202
    body = paid.json()

    database_path = db_session.get_bind().url.database
    reopened_engine = create_engine(
        URL.create("sqlite", database=database_path),
        connect_args={"check_same_thread": False},
    )
    original_factory = x402_module.SessionLocal
    x402_module.SessionLocal = sessionmaker(
        bind=reopened_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        result = client.get(
            body["result_endpoint"],
            headers={"X-PRAMA-Result-Capability": body["result_capability"]},
        )
    finally:
        x402_module.SessionLocal = original_factory
        reopened_engine.dispose()

    assert result.status_code == 200
    assert result.json()["mandate_id"] == body["mandate_id"]
    assert facilitator_stub.settle_calls == 1
