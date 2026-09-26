"""Offline API/SQL/ASGI integration of consumer fulfillment and authorization."""
import hashlib
import json
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.consumer_result import DELIVERY_EVENT, project_consumer_result, sanitize
from app.domain.mandates import (Mandate, AcquisitionTask, Evidence, InboundX402Payment,
                                 StructuralEvaluation, Decision, Ticket, UsageEvent, TelegraphCall, AutonomyPolicy)
from app.main import app
from app.persistence.database import get_session


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def store(monkeypatch, request):
    cert_url = os.environ.get("PRAMA_POSTGRES_CERT_URL")
    admin = None
    if cert_url:
        url = make_url(cert_url)
        if url.host not in {"postgres", "localhost", "127.0.0.1"} or url.database != "fulfillment_cert":
            raise RuntimeError("Certification requires the dedicated local database")
        database = "fulfillment_test_" + uuid.uuid4().hex
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}" TEMPLATE fulfillment_cert'))
        engine = create_engine(url.set(database=database))
        def cleanup_database():
            engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            admin.dispose()
        request.addfinalizer(cleanup_database)
    else:
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        for model in (Mandate, AcquisitionTask, Evidence, InboundX402Payment,
                      StructuralEvaluation, Decision, Ticket, UsageEvent, TelegraphCall, AutonomyPolicy):
            model.__table__.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    import app.api.x402 as x402
    import app.tickets.delivery as delivery
    monkeypatch.setattr(x402, "SessionLocal", factory)
    monkeypatch.setattr(delivery, "SessionLocal", factory)
    def dependency():
        with factory() as session:
            yield session
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = dependency
    with factory() as session:
        for mid in ("a", "b"):
            session.add(Mandate(mandate_id=mid, actor_id="x402-public", text="question", mandate_type="GENERAL",
                                constraints={}, max_budget_usdc=0.01, origin="M2M", status="TICKETED"))
            session.flush()
            session.add(InboundX402Payment(request_id=mid, mandate_id=mid, payer_wallet_address="payer",
                recipient_wallet_address="recipient", network="test", asset="test", amount_usdc=0.01,
                facilitator="offline", payment_status="SETTLED", idempotency_key=mid,
                result_capability_hash=hashlib.sha256(("cap-" + mid).encode()).hexdigest()))
            for number in range(2):
                aid = mid + str(number)
                session.add(AcquisitionTask(acquisition_id=aid, mandate_id=mid, query="question",
                    requested_intent="WEB_SEARCH", status="SUCCEEDED", ordinal=number))
                session.flush()
                session.add(Evidence(evidence_id="e" + aid, mandate_id=mid, acquisition_id=aid,
                    evidence_type="TELEGRAPH_RESULT", source_kind="TELEGRAPH", normalizer_version="telegraph-evidence-v0",
                    normalized_payload={"result": {"answer": aid, "url": "https://example.org/rfc"},
                                        "raw_response": "PRIVATE TRANSPORT"},
                    content_hash="0x" + "a" * 64, provenance_status="VERIFIED", admissibility="ADMITTED"))
        session.commit()
        yield session, TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)
    engine.dispose()


def result(client, mid="a", cap="cap-a"):
    return client.get(f"/v1/public/ask/{mid}/result", headers={"X-PRAMA-Result-Capability": cap})


def test_m2m_result_returns_admitted_intelligence_multiple_acquisitions_scoped_correctly(store):
    session, client = store
    body = result(client).json()
    rows = body["consumer_result"]["results"]
    assert body["consumer_result"]["status"] == "DELIVERED"
    assert [(r["acquisition_id"], r["evidence_id"], r["content"]["answer"]) for r in rows] == [
        ("a0", "ea0", "a0"), ("a1", "ea1", "a1")]
    assert all(r["evidence_content_hash"] == "0x" + "a" * 64 for r in rows)
    assert "PRIVATE TRANSPORT" not in json.dumps(body)
    assert "eb0" not in json.dumps(body)
    assert set(body) == {"request_id", "mandate_id", "origin", "status", "text", "created_at", "updated_at",
                         "result_endpoint", "acquisitions", "evidence", "evaluation", "decision", "ticket", "consumer_result"}


def test_m2m_result_preserves_governance_envelope(store):
    session, client = store
    session.add(StructuralEvaluation(evaluation_id="eval", mandate_id="a", evaluator="test",
        evaluator_version="v0", evidence_set_hash="unchanged", admitted_evidence_ids=["ea0"],
        limited_evidence_ids=[], rejected_evidence_ids=[], limitation_codes=[], contradiction_codes=[],
        structural_state="STRUCTURALLY_VALID", evaluation_payload={}))
    session.add(Decision(decision_id="decision", mandate_id="a", evaluation_id="eval", state="PERMIT",
        policy_version="prama-gate-v0", evidence_set_hash="unchanged", reason_codes=["OK"], decision_payload={}))
    session.add(Ticket(ticket_id="ticket", mandate_id="a", decision_id="decision", schema_version="prama.ticket.v0",
        canonical_payload={}, ticket_hash="original-ticket-hash", hash_algorithm="keccak256", anchor_status="LOCAL_ONLY"))
    session.commit()
    body = result(client).json()
    assert body["evaluation"] == {"evaluation_id": "eval", "structural_state": "STRUCTURALLY_VALID",
                                   "limitation_codes": [], "contradiction_codes": []}
    assert body["decision"] == {"decision_id": "decision", "state": "PERMIT", "policy_version": "prama-gate-v0",
                                 "reason_codes": ["OK"]}
    assert body["ticket"] == {"ticket_id": "ticket", "ticket_hash": "original-ticket-hash",
        "schema_version": "prama.ticket.v0", "hash_algorithm": "keccak256", "anchor_status": "LOCAL_ONLY"}


@pytest.mark.parametrize("cap", ["", "wrong", "cap-b"])
def test_m2m_result_missing_wrong_cross_mandate_capability_denied(store, cap):
    session, client = store
    assert result(client, cap=cap).status_code == 404
    assert session.query(UsageEvent).count() == 0
    assert client.get("/v1/public/ask/a/result", headers={"Authorization": "Bearer cap-a"}).status_code == 404


@pytest.mark.parametrize("status,expected", [("ACQUIRING", "PENDING"), ("DECIDED", "PENDING"),
                                           ("FAILED", "NOT_AVAILABLE"), ("TICKETED", "NOT_AVAILABLE")])
def test_m2m_result_pending_or_terminal_without_content(store, status, expected):
    session, client = store
    session.get(Mandate, "a").status = status
    for row in session.query(Evidence).filter_by(mandate_id="a"):
        row.normalized_payload = {"result": {"api_key": "only-secret"}}
    session.commit()
    assert result(client).json()["consumer_result"] == {"status": expected, "results": []}
    assert session.query(UsageEvent).count() == 0


@pytest.mark.parametrize("field,value", [("admissibility", "REJECTED"), ("admissibility", "LIMITED"),
                                        ("provenance_status", "FAILED"), ("acquisition_id", "b0"),
                                        ("mandate_id", "b")])
def test_m2m_result_never_returns_ineligible_or_other_mandate_evidence(store, field, value):
    session, client = store
    setattr(session.get(Evidence, "ea0"), field, value)
    session.commit()
    assert [r["evidence_id"] for r in result(client).json()["consumer_result"]["results"]] == ["ea1"]


def test_m2m_result_redacts_secrets_preserves_normal_intelligence(store, monkeypatch):
    session, client = store
    monkeypatch.setenv("TEST_API_KEY", "configured-secret")
    row = session.get(Evidence, "ea0")
    row.normalized_payload = {"result": {"price": 0, "rain": False, "url": "https://example.org/a",
        "nested": [{"Authorization": "Bearer hidden", "paymentSignature": "hidden", "seed_phrase": "hidden",
                    "result_capability": "hidden", "cookies": "hidden", "internal_headers": "hidden",
                    "facilitator_credentials": "hidden", "database_url": "hidden", "raw_response": "hidden",
                    "privateKey": "hidden", "API-key": "hidden", "text": "answer configured-secret cap-a"}]}}
    session.commit()
    content = result(client).json()["consumer_result"]["results"][0]["content"]
    assert content == {"price": 0, "rain": False, "url": "https://example.org/a",
                       "nested": [{"text": "answer [REDACTED] [REDACTED]"}]}
    session.expire_all()
    assert session.get(Evidence, "ea0").normalized_payload["result"]["nested"][0]["privateKey"] == "hidden"
    assert session.get(Evidence, "ea0").content_hash == "0x" + "a" * 64


@pytest.mark.parametrize("headers", [{}, {"X-PRAMA-Result-Capability": "cap-a"},
                                     {"X-PRAMA-Result-Capability": "cap-b"}, {"Authorization": "Bearer anything"}])
def test_m2m_generic_evidence_no_auth_or_capability_bypass(store, headers):
    session, client = store
    response = client.get("/v1/mandates/a/evidence", headers=headers)
    assert response.status_code == 403
    assert "normalized_payload" not in response.text


def test_user_and_autonomous_evidence_auth_behavior_unchanged(store, monkeypatch):
    session, client = store
    mandate = session.get(Mandate, "a")
    mandate.origin = "USER"
    session.commit()
    assert client.get("/v1/mandates/a/evidence").status_code == 401
    import app.users.auth as auth
    monkeypatch.setattr(auth, "current_user", lambda *args: SimpleNamespace(user_id="other"))
    assert client.get("/v1/mandates/a/evidence").status_code == 404
    monkeypatch.setattr(auth, "current_user", lambda *args: SimpleNamespace(user_id="x402-public"))
    assert client.get("/v1/mandates/a/evidence").status_code == 200
    mandate.origin = "AUTONOMOUS"
    session.commit()
    assert client.get("/v1/mandates/a/evidence").status_code == 200


def test_delivery_event_append_semantics_no_capability_plaintext(store):
    session, client = store
    for _ in range(2):
        assert result(client).status_code == 200
    events = session.query(UsageEvent).all()
    assert len(events) == 2
    assert all(e.event_type == DELIVERY_EVENT and e.created_at for e in events)
    for event in events:
        assert event.metadata_["acquisition_ids"] == ["a0", "a1"]
        assert event.metadata_["evidence_ids"] == ["ea0", "ea1"]
        assert "cap-a" not in json.dumps(event.metadata_)
    from app.api.public_surfaces import _execution_history
    assert sum(row["delivery_status"] == "DELIVERED" for row in
               _execution_history(session, session.query(Mandate).all())) == 2


def test_postgres_concurrent_polling_no_duplicate_fulfillment(store):
    session, client = store
    if session.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency certification")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: result(client), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert session.query(UsageEvent).count() == 8
    assert session.query(AcquisitionTask).count() == 4
    assert session.query(InboundX402Payment).count() == 2
    from app.api.public_surfaces import _execution_history
    assert sum(row["delivery_status"] == "DELIVERED" for row in
               _execution_history(session, session.query(Mandate).all())) == 2


def test_postgres_delivery_write_failure_does_not_break_content(store):
    session, client = store
    if session.bind.dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction failure certification")
    session.execute(text("ALTER TABLE usage_events ADD CONSTRAINT cert_reject_delivery CHECK (event_type <> 'M2M_CONSUMER_RESULT_DELIVERED')"))
    session.commit()
    response = result(client)
    assert response.status_code == 200
    assert response.json()["consumer_result"]["status"] == "DELIVERED"
    assert session.query(UsageEvent).count() == 0
    assert session.query(AcquisitionTask).count() == 4
    assert session.query(InboundX402Payment).count() == 2


def test_read_model_delivery_derived_from_real_event(store):
    from app.api.public_surfaces import _execution_history
    session, client = store
    mandates = session.query(Mandate).all()
    assert {r["delivery_status"] for r in _execution_history(session, mandates)} == {"UNKNOWN"}
    result(client)
    rows = _execution_history(session, mandates)
    assert sum(r["delivery_status"] == "DELIVERED" for r in rows) == 2
    assert sum(r["delivery_status"] == "UNKNOWN" for r in rows) == 2


def test_delivery_event_not_recorded_on_failed_send(monkeypatch):
    import asyncio
    import app.tickets.delivery as delivery
    calls = []
    monkeypatch.setattr(delivery, "record_consumer_delivery", lambda *args: calls.append(args))
    response = delivery.ConsumerResultResponse({"mandate_id": "a", "consumer_result": {
        "status": "DELIVERED", "results": [{"acquisition_id": "a0", "evidence_id": "ea0"}]}})
    async def broken_send(message):
        if message["type"] == "http.response.body":
            raise OSError("disconnected")
    with pytest.raises(OSError):
        asyncio.run(response({"type": "http"}, None, broken_send))
    assert calls == []


def test_delivery_commit_failure_does_not_invent_receipt(store, monkeypatch):
    session, client = store
    import app.tickets.delivery as delivery
    def unavailable(*args):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(delivery, "record_consumer_delivery", unavailable)
    response = result(client)
    assert response.status_code == 200
    assert response.json()["consumer_result"]["status"] == "DELIVERED"
    assert session.query(UsageEvent).count() == 0


def test_partial_delivery_event_only_covers_included_acquisitions(store):
    session, client = store
    session.get(Evidence, "ea1").admissibility = "REJECTED"
    session.commit()
    result(client)
    event = session.query(UsageEvent).one()
    assert event.metadata_["acquisition_ids"] == ["a0"]
    assert event.metadata_["evidence_ids"] == ["ea0"]


def test_secret_strings_and_urls_are_sanitized():
    clean = sanitize({"answer": "Authorization: Bearer hidden", "db": "postgresql://u:p@localhost/db",
                      "url": "https://example.org/data?api_key=hidden&symbol=NVDA"})
    assert "hidden" not in json.dumps(clean)
    assert "u:p" not in json.dumps(clean)
    assert "symbol=NVDA" in clean["url"]


@pytest.mark.parametrize("value", [None, {}, [], "", "   ", {"text": "[REDACTED]"}])
def test_delivered_only_when_content_included(value):
    mandate = SimpleNamespace(mandate_id="a", status="TICKETED")
    task = SimpleNamespace(mandate_id="a", acquisition_id="a0", requested_intent="WEB_SEARCH")
    evidence = SimpleNamespace(mandate_id="a", acquisition_id="a0", evidence_id="e", content_hash="unchanged",
        admissibility="ADMITTED", provenance_status="VERIFIED", normalized_payload={"result": value})
    assert project_consumer_result(mandate, [task], [evidence])["status"] == "NOT_AVAILABLE"
