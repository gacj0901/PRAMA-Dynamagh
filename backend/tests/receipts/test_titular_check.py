"""Real isolated PostgreSQL; only Turnstile HTTP transport is simulated."""
import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.main import app
from app.api.m2m import _m2m_context_id
from app.domain.mandates import AgentIdentity, Mandate, AcquisitionTask, TelegraphCall, Evidence, StructuralEvaluation, Decision, Ticket, UsageEvent
from app.persistence.database import get_session
from app.pramagraph.evaluation import digest, decide
from app.tickets.service import issue
from app.tickets.disclosure import append_event, delivered, events_for_agent, utcnow, VERSION
from app.agents.disclosure_memory import build_disclosure_memory, replay_disclosure
from app.tickets import human_presence, delivery

TOKEN = "isolated-m2m-receipt-test"
AUTH = {"Authorization": "Bearer " + TOKEN}
ORIGIN = {"Origin": "https://receipt.test"}


@pytest.fixture
def fixture(monkeypatch):
    url = os.environ.get("TITULAR_TEST_DATABASE_URL", "")
    if "@127.0.0.1:55439/prama_titular_test" not in url:
        pytest.skip("Dedicated local TITULAR_TEST_DATABASE_URL required")
    engine = create_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", TOKEN)
    monkeypatch.setenv("TURNSTILE_SITE_KEY", "test-site")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "private-turnstile-fixture-secret")
    monkeypatch.setenv("TITULAR_CHECK_SESSION_SECRET", "receipt-session-fixture-secret-32-characters")
    monkeypatch.setenv("TITULAR_CHECK_ALLOWED_HOSTS", "receipt.test")
    monkeypatch.setenv("TITULAR_CHECK_PRESENTATION_DEADLINE_SECONDS", "30")
    def get_db(): yield session
    @contextmanager
    def delivery_db(): yield session
    app.dependency_overrides[get_session] = get_db
    monkeypatch.setattr(delivery, "SessionLocal", delivery_db)
    suffix = uuid.uuid4().hex[:10]
    identity = AgentIdentity(agent_id="agent-" + suffix, name="fixture", origin="EXTERNAL_API_AGENT", status="ACTIVE", trajectory_version="g13-agent-identity-v1", m2m_context_id=_m2m_context_id(TOKEN))
    session.add(identity); session.flush()
    mandate = Mandate(actor_id="secret-actor", agent_id=identity.agent_id, agent_identity_id=identity.agent_id, client_id="private-client", m2m_context_id=_m2m_context_id(TOKEN), text="PRIVATE_MANDATE_SENTINEL", mandate_type="GENERAL", constraints={}, max_budget_usdc=Decimal("0.05"), status="DECIDED", origin="M2M")
    session.add(mandate); session.flush()
    task = AcquisitionTask(mandate_id=mandate.mandate_id, query=mandate.text, requested_intent="CRYPTO_PRICE", status="SUCCEEDED", ordinal=0)
    session.add(task); session.flush()
    call = TelegraphCall(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, causal_request_id=str(uuid.uuid4()), miner_id="miner-fixture", miner_name="Fixture miner", intent="CRYPTO_PRICE", signal_hash="0x" + "b" * 64, cost_usd=Decimal("0.01"), duration_ms=0, status="SUCCEEDED", raw_response={"result": "RAW_PROVIDER_SENTINEL", "authorization": "BEARER_SECRET_SENTINEL", "gateway": "http://PRIVATE_GATEWAY_SENTINEL"})
    session.add(call); session.flush()
    payload = {"price": 100, "private_field": "NORMALIZED_PAYLOAD_SENTINEL"}
    evidence = Evidence(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, telegraph_call_id=call.telegraph_call_id, evidence_type="TELEGRAPH", source_kind="TELEGRAPH_HTTP", source_intent=call.intent, source_miner_id=call.miner_id, source_signal_hash=call.signal_hash, normalized_payload=payload, content_hash=digest(payload), normalizer_version="fixture-v0", provenance_status="VERIFIED", admissibility="ADMITTED", limitation_codes=[])
    session.add(evidence); session.flush()
    evaluation = StructuralEvaluation(mandate_id=mandate.mandate_id, evaluator="PRAMAGRAPH", evaluator_version="pramagraph-structural-v0", evidence_set_hash=digest([evidence.content_hash]), admitted_evidence_ids=[evidence.evidence_id], limited_evidence_ids=[], rejected_evidence_ids=[], limitation_codes=[], contradiction_codes=[], structural_state="STRUCTURALLY_ADMISSIBLE", evaluation_payload={})
    session.add(evaluation); session.flush()
    state, reasons = decide(evaluation.structural_state)
    decision = Decision(mandate_id=mandate.mandate_id, evaluation_id=evaluation.evaluation_id, state=state, policy_version="prama-gate-v0", evidence_set_hash=evaluation.evidence_set_hash, reason_codes=reasons, decision_payload={})
    session.add(decision); session.commit()
    client = TestClient(app, base_url="https://receipt.test")
    f = SimpleNamespace(session=session, client=client, mandate=mandate, identity=identity, evidence=evidence, decision=decision, task=task, call=call, ticket=None, engine=engine)
    def mint():
        f.ticket = issue(session, mandate.mandate_id)[0]
        f.hash = f.ticket.ticket_hash[2:]
        f.slug = f.hash + "-prama-dynamagh"
        f.path = "/v1/titular-check/" + f.slug
        f.url = "/titular-check/" + f.slug
        return f.ticket
    f.mint = mint
    def cloudflare(request, timeout):
        assert request.full_url == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
        assert json.loads(request.data)["response"] == "ephemeral-test-token"
        result = {"success": True, "hostname": "receipt.test", "action": "titular_check", "cdata": f.hash}
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return json.dumps(result).encode()
        return Reply()
    monkeypatch.setattr(human_presence, "urlopen", cloudflare)
    try: yield f
    finally:
        app.dependency_overrides.clear()
        session.close(); transaction.rollback(); connection.close(); engine.dispose()


def count(f, name):
    return f.session.query(UsageEvent).filter_by(event_type=name).count()


def access(f):
    result = f.client.post(f.path + "/challenge", json={"token": "ephemeral-test-token"}, headers=ORIGIN)
    assert result.status_code == 200, result.text
    return {**ORIGIN, "Authorization": "Bearer " + result.json()["access_token"]}


def send_to_agent(f):
    result = f.client.get("/v1/m2m/mandates/" + f.mandate.mandate_id, headers=AUTH)
    assert result.status_code == 200, result.text
    return result.json()


def present(f, **changes):
    payload = {"response_hash": f.ticket.ticket_hash, "url": f.url, "presentation_context": "interaction-fixture", **changes}
    return f.client.post("/v1/m2m/titular-check/presented", headers=AUTH, json=payload)


def test_issued_pending_delivery_contract_and_idempotency(fixture):
    f = fixture
    assert send_to_agent(f)["titular_check"] == {"status": "PENDING", "response_hash": None, "url": None}
    f.mint()
    assert count(f, "TITULAR_CHECK_ISSUED") == 1
    f.mint()
    assert count(f, "TITULAR_CHECK_ISSUED") == 1
    assert count(f, "TITULAR_CHECK_DELIVERED_TO_AGENT") == 0
    result = send_to_agent(f)
    assert result["titular_check"] == {"status": "AVAILABLE", "response_hash": f.ticket.ticket_hash, "url": f.url}
    assert f.ticket.ticket_id not in f.url
    send_to_agent(f)
    ticket_read = f.client.get("/v1/m2m/tickets/" + f.ticket.ticket_id, headers=AUTH)
    assert ticket_read.json()["titular_check"] == result["titular_check"]
    assert count(f, "TITULAR_CHECK_DELIVERED_TO_AGENT") == 1


@pytest.mark.parametrize("slug", ["1", str(uuid.uuid4()), "a"*64, "a"*63+"-prama-dynamagh", "z"*64+"-prama-dynamagh", "a"*64+"-wrong", "0x"+"a"*64+"-prama-dynamagh", "A"*64+"-prama-dynamagh"])
def test_invalid_locator(fixture, slug):
    assert fixture.client.get("/v1/titular-check/" + slug).status_code == 404


def test_gate_crawler_privacy_reconstruction_read_and_ack(fixture):
    f = fixture; f.mint()
    assert f.client.get(f.path).status_code == 403
    assert count(f, "TITULAR_CHECK_OPENED_BY_TITULAR") == 0
    original = copy.deepcopy(f.ticket.canonical_payload)
    headers = access(f)
    assert count(f, "HUMAN_PRESENCE_VERIFIED") == 1
    assert count(f, "TITULAR_CHECK_OPENED_BY_TITULAR") == 0
    assert f.client.post(f.path + "/acknowledge", headers=headers).status_code == 409
    response = f.client.get(f.path, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["verification"] == {"status": "VALID", "payload_hash_match": True, "source_artifacts_match": True, "reconstructed_hash": f.ticket.ticket_hash}
    assert result["replay"]["status"] == "VALID"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"
    for secret in ("PRIVATE_MANDATE_SENTINEL", "RAW_PROVIDER_SENTINEL", "BEARER_SECRET_SENTINEL", "PRIVATE_GATEWAY_SENTINEL", "NORMALIZED_PAYLOAD_SENTINEL", f.ticket.ticket_id, "ephemeral-test-token"):
        assert secret not in response.text
        if secret != f.ticket.ticket_id:
            assert secret not in str([e.metadata_ for e in f.session.query(UsageEvent).all()])
    # Internal ticket IDs are expected only in audit metadata, not public output.
    f.client.get(f.path, headers=headers)
    assert count(f, "TITULAR_CHECK_OPENED_BY_TITULAR") == 1
    assert count(f, "TITULAR_CHECK_VERIFIED_BY_TITULAR") == 2
    ack = f.client.post(f.path + "/acknowledge", headers=headers)
    assert ack.json()["action_approval"] is False
    assert f.client.post(f.path + "/acknowledge", headers=headers).json()["event_id"] == ack.json()["event_id"]
    assert count(f, "TITULAR_CHECK_ACKNOWLEDGED_BY_TITULAR") == 1
    f.session.refresh(f.ticket)
    assert f.ticket.canonical_payload == original
    for model in (Ticket, Evidence, Decision, AcquisitionTask, TelegraphCall, Mandate):
        assert f.session.query(model).count() == 1


@pytest.mark.parametrize("mutation", ["payload", "evidence", "source", "hash"])
def test_mutation_fails(fixture, mutation):
    f = fixture; f.mint(); headers = access(f)
    if mutation == "payload": f.ticket.canonical_payload = {**f.ticket.canonical_payload, "decorative": True}
    if mutation == "evidence": f.evidence.normalized_payload = {"tampered": True}
    if mutation == "source": f.call.miner_id = "changed-miner"
    if mutation == "hash": f.ticket.ticket_hash = "0x" + "f" * 64
    f.session.commit()
    result = f.client.get(f.path, headers=headers)
    if mutation == "hash": assert result.status_code == 404
    else: assert result.json()["verification"]["status"] == "INVALID"
    assert count(f, "TITULAR_CHECK_VERIFIED_BY_TITULAR") == 0


def test_unconfigured_invalid_challenge_and_cross_hash_grants(fixture, monkeypatch):
    f = fixture; f.mint()
    monkeypatch.setattr(human_presence, "siteverify", lambda token: {"success": False})
    assert f.client.post(f.path+"/challenge", headers=ORIGIN, json={"token":"bad"}).status_code == 403
    assert count(f, "HUMAN_PRESENCE_VERIFIED") == 0
    monkeypatch.delenv("TURNSTILE_SECRET_KEY")
    assert f.client.get("/v1/titular-check/config").status_code == 503
    assert f.client.get(f.path).status_code == 503


def test_disclosure_replay_cross_read_no_principal_penalty(fixture):
    f=fixture; f.mint(); send_to_agent(f)
    assert present(f).status_code == 200
    assert present(f).status_code == 200
    before = build_disclosure_memory(f.session, f.identity.agent_id, as_of=utcnow()+timedelta(seconds=31))
    assert before["compliance"] == 1 and before["eligible"] == 1
    assert count(f, "TITULAR_CHECK_PRESENTED_BY_AGENT") == 1
    headers=access(f); f.client.get(f.path, headers=headers)
    after=build_disclosure_memory(f.session, f.identity.agent_id, as_of=utcnow()+timedelta(seconds=31))
    assert after["compliance"] == before["compliance"]
    assert after["titular_checks_opened"] == 1 and after["titular_checks_acknowledged"] == 0
    events=events_for_agent(f.session, f.identity.agent_id)
    cutoff=utcnow()+timedelta(seconds=31)
    assert replay_disclosure(events, as_of=cutoff) == replay_disclosure(list(reversed(events)), as_of=cutoff)
    result=f.client.get(f"/v1/agent-identities/{f.identity.agent_id}/disclosure", headers=AUTH)
    assert result.status_code == 200, result.text
    assert result.json()["observer"] == "O_AGENT"
    assert result.json()["memory"]["g13_signal"] == "AVAILABLE_POLICY_SIGNAL"
    assert result.json()["memory"]["compliance"] == 1


def test_missing_deadline_grace_and_late_presentation(fixture, monkeypatch):
    f=fixture; f.mint(); send_to_agent(f)
    now=utcnow()
    assert build_disclosure_memory(f.session,f.identity.agent_id,as_of=now)["compliance"] is None
    later=now+timedelta(seconds=31)
    result=build_disclosure_memory(f.session,f.identity.agent_id,as_of=later)
    assert result["missing"] == 1 and result["compliance"] == 0
    monkeypatch.setattr("app.tickets.disclosure.utcnow",lambda:later)
    assert present(f,presented_at=(now-timedelta(days=1)).isoformat()).status_code==200
    result=build_disclosure_memory(f.session,f.identity.agent_id,as_of=later)
    assert result["late"]==1 and result["compliance"]==0


def test_wrong_hash_url_delivery_and_ambiguous_identity(fixture):
    f=fixture; f.mint()
    assert present(f).status_code == 409
    send_to_agent(f)
    assert present(f,response_hash="0x"+"c"*64).status_code==404
    assert present(f,url=f.url+"?changed=1").status_code==422
    assert count(f,"TITULAR_CHECK_PRESENTED_BY_AGENT")==0
    assert count(f,"TITULAR_CHECK_PRESENTATION_INVALID")==3
    other=AgentIdentity(agent_id="second",name="second",origin="EXTERNAL_API_AGENT",status="ACTIVE",trajectory_version="g13-agent-identity-v1",m2m_context_id=f.identity.m2m_context_id)
    f.session.add(other);f.session.commit()
    before=f.session.query(UsageEvent).count()
    result=present(f)
    assert result.status_code==409 and result.json()["detail"]=="DISCLOSURE_AGENT_CONTEXT_AMBIGUOUS"
    assert f.session.query(UsageEvent).count()==before


@pytest.mark.parametrize("sql", [
    "UPDATE usage_events SET event_type='changed' WHERE metadata->>'schema_version'='titular-disclosure-v0'",
    "UPDATE usage_events SET metadata='{}'::jsonb WHERE metadata->>'schema_version'='titular-disclosure-v0'",
    "DELETE FROM usage_events WHERE metadata->>'schema_version'='titular-disclosure-v0'",
    "TRUNCATE usage_events",
])
def test_database_rejects_direct_mutation(fixture,sql):
    f=fixture;f.mint()
    with pytest.raises(DBAPIError,match="append-only"):
        with f.session.begin_nested(): f.session.execute(text(sql))
    assert count(f,"TITULAR_CHECK_ISSUED")==1
    replay_disclosure(events_for_agent(f.session,f.identity.agent_id),as_of=utcnow())


def test_hash_without_prefix_missing_hash_and_wrong_grant(fixture):
    f=fixture; f.mint()
    f.ticket.ticket_hash=f.hash; f.session.commit()
    headers=access(f)
    result=f.client.get(f.path,headers=headers)
    assert result.status_code==200
    assert result.json()["response_hash"]==f.hash
    assert result.json()["verification"]["payload_hash_match"] is True
    other="/v1/titular-check/"+"c"*64+"-prama-dynamagh"
    assert f.client.get(other,headers=headers).status_code==403
    f.hash="c"*64
    assert f.client.post(other+"/challenge",headers=ORIGIN,json={"token":"ephemeral-test-token"}).status_code==404


@pytest.mark.parametrize("field,value", [("success",False),("hostname","attacker.test"),("action","other"),("cdata","b"*64)])
def test_turnstile_checks_provider_success_hostname_action_and_hash(fixture,monkeypatch,field,value):
    f=fixture;f.mint()
    result={"success":True,"hostname":"receipt.test","action":"titular_check","cdata":f.hash,field:value}
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,size):return json.dumps(result).encode()
    monkeypatch.setattr(human_presence,"urlopen",lambda *args,**kwargs:Reply())
    response=f.client.post(f.path+"/challenge",headers=ORIGIN,json={"token":"ephemeral-test-token"})
    assert response.status_code==403
    assert count(f,"TITULAR_CHECK_OPENED_BY_TITULAR")==0
    assert count(f,"HUMAN_PRESENCE_VERIFIED")==0


def test_rate_limit_is_persistent_and_crawlers_never_open(fixture):
    f=fixture;f.mint()
    for _ in range(60):assert f.client.get(f.path).status_code==403
    assert f.client.get(f.path).status_code==429
    assert count(f,"TITULAR_CHECK_OPENED_BY_TITULAR")==0
    assert count(f,"TITULAR_CHECK_ACCESS_ATTEMPT")==60


def test_foreign_identity_cannot_claim_receipt(fixture):
    f=fixture;f.mint();send_to_agent(f)
    f.identity.m2m_context_id="foreign-context"
    second=AgentIdentity(agent_id="caller-other",name="other",origin="EXTERNAL_API_AGENT",status="ACTIVE",trajectory_version="g13-agent-identity-v1",m2m_context_id=_m2m_context_id(TOKEN))
    f.session.add(second);f.session.commit()
    assert present(f).status_code==404
    assert count(f,"TITULAR_CHECK_PRESENTED_BY_AGENT")==0
    anomalies=f.session.query(UsageEvent).filter_by(event_type="TITULAR_CHECK_PRESENTATION_INVALID").all()
    assert len(anomalies)==1 and anomalies[0].metadata_["agent_identity_id"]==second.agent_id
    assert anomalies[0].mandate_id is None


def test_second_operation_uses_prior_history_and_o_agent_stream(fixture):
    from sqlalchemy import inspect
    from app.agents.observation import build_o_agent_stream
    f=fixture;f.mint();send_to_agent(f);assert present(f).status_code==200
    def clone(row,**changes):
        values={a.key:copy.deepcopy(getattr(row,a.key)) for a in inspect(type(row)).column_attrs}
        for column in inspect(type(row)).primary_key:values.pop(column.key)
        values.update(changes)
        result=type(row)(**values);f.session.add(result);f.session.flush();return result
    m=clone(f.mandate,status="DECIDED")
    task=clone(f.task,mandate_id=m.mandate_id)
    call=clone(f.call,mandate_id=m.mandate_id,acquisition_id=task.acquisition_id)
    evidence=clone(f.evidence,mandate_id=m.mandate_id,acquisition_id=task.acquisition_id,telegraph_call_id=call.telegraph_call_id)
    evaluation=f.session.get(StructuralEvaluation,f.decision.evaluation_id)
    ev=clone(evaluation,mandate_id=m.mandate_id,admitted_evidence_ids=[evidence.evidence_id])
    clone(f.decision,mandate_id=m.mandate_id,evaluation_id=ev.evaluation_id)
    f.session.commit();issue(f.session,m.mandate_id)
    assert f.client.get("/v1/m2m/mandates/"+m.mandate_id,headers=AUTH).status_code==200
    cutoff=utcnow()+timedelta(seconds=31)
    result=build_disclosure_memory(f.session,f.identity.agent_id,as_of=cutoff)
    assert result["eligible"]==2 and result["missing"]==1 and result["compliance"]==0.5
    events=events_for_agent(f.session,f.identity.agent_id)
    assert result==replay_disclosure(events,as_of=cutoff)
    stream=build_o_agent_stream(f.session,f.identity.agent_id)
    assert any(row.facts.action_status=="TITULAR_CHECK_PRESENTED_BY_AGENT" for row in stream)
    # A formal Gamma row has no input position in this versioned projection.
    f.session.add(UsageEvent(mandate_id=m.mandate_id,event_type="FORMAL_GAMMA",metadata_={"agent_identity_id":f.identity.agent_id,"Gamma":{"Xi":9999}}));f.session.commit()
    assert build_disclosure_memory(f.session,f.identity.agent_id,as_of=cutoff)==result


@pytest.mark.asyncio
async def test_failed_transport_send_is_not_delivery(fixture):
    from app.tickets.delivery import DisclosureMiddleware
    f=fixture;f.mint()
    async def inner(scope,receive,send):
        await send({"type":"http.response.start","status":200,"headers":[]})
        await send({"type":"http.response.body","body":json.dumps({"titular_check":{"status":"AVAILABLE","response_hash":f.ticket.ticket_hash,"url":f.url}}).encode()})
    async def failed_send(message):
        if message["type"]=="http.response.body":raise OSError("fixture socket failure")
    with pytest.raises(OSError):
        await DisclosureMiddleware(inner)({"type":"http","path":"/v1/m2m/mandates/example","headers":[(b"authorization",("Bearer "+TOKEN).encode())]},None,failed_send)
    assert count(f,"TITULAR_CHECK_DELIVERED_TO_AGENT")==0
