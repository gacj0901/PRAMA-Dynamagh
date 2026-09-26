import base64
import json
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from app.main import app
from app.api import x402
from app.api.agent_access import descriptor, bazaar_extension, REQUEST_SCHEMA
from app.api.adoption import adoption_snapshot, PROOF_HASH
from app.domain.mandates import AgentIdentity, Mandate, UsageEvent, Evidence
from tests.unit.test_m2m_consumer_result import store, result
from tests.unit.test_x402_public import db_session, facilitator_stub, _valid_payment_header


@pytest.mark.parametrize("path,fragment", [
    ("/.well-known/prama-agent.json", "PRAMA descriptor"),
    ("/agents.md", "[BENIGN AGENT DISCOVERY]"), ("/llms.txt", "Telegraph-powered"),
])
def test_discovery_documents_available(path, fragment):
    response = TestClient(app).get(path)
    assert response.status_code == 200
    assert fragment in response.text


def test_manifest_config_derived_and_no_false_identity_claim(monkeypatch):
    monkeypatch.setattr(x402, "PUBLIC_ORIGIN", "https://example.org")
    value = descriptor()
    assert value["interfaces"]["http"]["endpoint"] == "https://example.org/v1/public/ask"
    assert value["payments"]["network"] == x402.X402_NETWORK
    assert value["payments"]["asset_contract"] == x402.X402_ASSET
    assert value["payments"]["environment"] == "TESTNET"
    assert value["identity"]["wallet_is_agent_identity"] is False
    assert value["discovery"]["bazaar_indexing_confirmed"] is False
    assert "private_key" not in json.dumps(value)


def test_bazaar_schema_valid_and_does_not_change_payment_terms():
    requirements = x402._requirements()
    response = TestClient(app).post("/v1/public/ask", json={"requested_intent": "WEB_SEARCH", "query": "test"})
    assert response.status_code == 402
    body = response.json()
    assert body == json.loads(base64.b64decode(response.headers["PAYMENT-REQUIRED"]))
    assert body["accepts"] == [requirements]
    extension = body["extensions"]["bazaar"]
    Draft202012Validator.check_schema(extension["schema"])
    Draft202012Validator(extension["schema"]).validate(extension["info"])
    assert extension["info"]["input"]["type"] == "http"
    assert extension["info"]["input"]["bodyType"] == "json"
    assert body["x402Version"] == 2
    assert requirements["amount"] == x402.X402_AMOUNT_ATOMIC
    assert requirements["scheme"] == "exact"
    assert body["resource"]["url"] == requirements["resource"]


def test_openapi_native_endpoints_document_real_request_and_result():
    schema = TestClient(app).get("/openapi.json").json()
    post = schema["paths"]["/v1/public/ask"]["post"]
    assert set(post["responses"]) >= {"202", "402"}
    for body in ({"intent": "WEB_SEARCH", "request": "need"}, {"requested_intent": "WEB_SEARCH", "query": "need"}):
        Draft202012Validator(REQUEST_SCHEMA).validate(body)
    assert not Draft202012Validator(REQUEST_SCHEMA).is_valid({"requested_intent": "WEB_SEARCH"})
    get = schema["paths"]["/v1/public/ask/{mandate_id}/result"]["get"]
    assert any(p["name"] == "X-PRAMA-Result-Capability" for p in get["parameters"])


def test_mcp_initialize_tools_list_and_discovery():
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
    with TestClient(app) as client:
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "offline-test", "version": "1"}}})
        assert response.status_code == 200
        assert "tools" in response.json()["result"]["capabilities"]
        response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert names == {"prama.discover", "prama.execution_guide", "prama.supported_capabilities"}
        for name in names:
            response = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": {}}})
            assert response.status_code == 200
            assert response.json()["result"].get("isError") is not True
            assert "payment_signature" not in response.text
        denied = client.post("/mcp", headers={**headers, "Origin": "https://evil.invalid"}, json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        assert denied.status_code in {400, 403}


def test_adoption_real_only_no_wallet_enumeration_no_poll_inflation(store):
    session, client = store
    AgentIdentity.__table__.create(session.bind, checkfirst=True)
    snapshot = adoption_snapshot(session)
    assert snapshot["metrics"] == {"external_m2m_requests": 2, "settled_m2m_requests": 2,
        "unique_paying_wallets": 1, "declared_client_labels": 0, "registered_m2m_agent_identities": 0,
        "successful_acquisitions": 4, "admitted_evidence": 4, "consumer_results_delivered": 0}
    for _ in range(3):
        assert result(client).status_code == 200
    assert adoption_snapshot(session)["metrics"]["consumer_results_delivered"] == 1
    before = session.query(UsageEvent).count()
    response = client.get("/v1/public/adoption")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=30"
    assert session.query(UsageEvent).count() == before
    assert "payer_wallet_address" not in response.text
    assert "cap-a" not in response.text
    assert "unique_agents" not in response.text
    assert response.json()["verified_execution"]["verification"] == "OPERATOR_ATTESTED"
    assert response.json()["verified_execution"]["evidence_content_hash"] == PROOF_HASH
    # Other origins do not count as external M2M activity.
    session.get(Mandate, "b").origin = "MANUAL"
    session.commit()
    assert adoption_snapshot(session)["metrics"]["external_m2m_requests"] == 1


def test_adoption_empty_database_does_not_count_operator_proof(store):
    session, client = store
    AgentIdentity.__table__.create(session.bind, checkfirst=True)
    for mandate in session.query(Mandate).all():
        mandate.origin = "MANUAL"
    session.commit()
    assert set(adoption_snapshot(session)["metrics"].values()) == {0}


def test_verified_execution_requires_persisted_lineage_and_event(store):
    from tests.unit.test_m2m_consumer_result import test_m2m_result_preserves_governance_envelope
    from app.domain.mandates import AcquisitionTask
    session, client = store
    AgentIdentity.__table__.create(session.bind, checkfirst=True)
    session.get(Mandate, "a").agent_id = "KIMI_EXTERNAL"
    session.get(AcquisitionTask, "a0").requested_intent = "WEATHER_FORECAST"
    session.get(Evidence, "ea0").content_hash = PROOF_HASH
    session.commit()
    assert adoption_snapshot(session)["verified_execution"]["verification"] == "OPERATOR_ATTESTED"
    test_m2m_result_preserves_governance_envelope(store)
    assert adoption_snapshot(session)["verified_execution"]["verification"] == "PERSISTED_LINEAGE_VERIFIED"


def test_requested_intent_alias_reaches_same_canonical_acquisition(db_session, facilitator_stub, monkeypatch):
    from app.domain.mandates import AcquisitionTask
    monkeypatch.setattr(x402.execute_acquisition, "delay", lambda *args: None)
    response = TestClient(app).post("/v1/public/ask", headers={"PAYMENT-SIGNATURE": _valid_payment_header()},
                                   json={"requested_intent": "WEATHER_FORECAST", "query": "actual test fixture need"})
    assert response.status_code == 202
    task = db_session.query(AcquisitionTask).one()
    assert task.requested_intent == "WEATHER_FORECAST"
    assert task.query == "actual test fixture need"
    assert facilitator_stub.verify_calls == facilitator_stub.settle_calls == 1
    assert facilitator_stub.verify_requirements == x402._requirements()


def test_delivery_does_not_establish_semantic_fulfillment():
    from app.api.consumer_result import DELIVERY_EVENT
    assert DELIVERY_EVENT == "M2M_CONSUMER_RESULT_DELIVERED"
    d = descriptor()
    assert d["semantics"]["delivered_implies_semantic_fulfillment"] is False
    assert "consumer_fulfillment_condition" not in d["semantics"]
    assert d["semantics"]["consumer_delivery_condition"] == "consumer_result.status == DELIVERED"
    for path in ("/agents.md", "/llms.txt"):
        assert "Semantic task fulfillment is not currently inferred from delivery." in TestClient(app).get(path).text
    observations = d["capabilities"]["intent_observations"]
    assert "retrieval primitive" in observations["WEB_SEARCH"]
    assert "investigating" in observations["RESEARCH_QUERY"]


def test_failed_research_not_delivered_but_web_search_delivery_counts(store):
    from app.domain.mandates import AcquisitionTask
    session, client = store
    AgentIdentity.__table__.create(session.bind, checkfirst=True)
    for task in session.query(AcquisitionTask).filter_by(mandate_id="b"):
        task.status = "FAILED"
        task.requested_intent = "RESEARCH_QUERY"
    for evidence in session.query(Evidence).filter_by(mandate_id="b"):
        session.delete(evidence)
    session.commit()
    assert result(client, "b", "cap-b").json()["consumer_result"]["status"] == "NOT_AVAILABLE"
    assert result(client).json()["consumer_result"]["status"] == "DELIVERED"
    snapshot = client.get("/v1/public/adoption").json()
    assert snapshot["metrics"]["consumer_results_delivered"] == 1
    assert "consumer_fulfilled" not in snapshot["metrics"]
    assert snapshot["semantic_task_fulfillment"] == "NOT_INFERRED_FROM_DELIVERY"


@pytest.mark.parametrize("origin", ["USER", "AUTONOMOUS", "MANUAL"])
def test_delivery_metric_keeps_m2m_origin_scope(store, origin):
    session, client = store
    AgentIdentity.__table__.create(session.bind, checkfirst=True)
    result(client)
    session.get(Mandate, "a").origin = origin
    session.commit()
    assert adoption_snapshot(session)["metrics"]["consumer_results_delivered"] == 0


def test_bazaar_confirmation_is_dated_catalog_evidence_not_declaration(monkeypatch):
    from app.api.bazaar_observation import indexing_observation, FACILITATOR, RESOURCE
    monkeypatch.setattr(x402, "PUBLIC_ORIGIN", RESOURCE.removesuffix("/v1/public/ask"))
    monkeypatch.setattr(x402, "X402_FACILITATOR", FACILITATOR)
    monkeypatch.setattr(x402, "X402_NETWORK", "eip155:84532")
    monkeypatch.setattr(x402, "_requirements", lambda: {"payTo": "0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6"})
    value = indexing_observation()
    assert value["bazaar_indexing_confirmed"] is True
    assert value["bazaar_indexing_observed_at"] and "/discovery/resources" in value["bazaar_discovery_reference"]
    monkeypatch.setattr(x402, "X402_FACILITATOR", "https://other.example")
    value = indexing_observation()
    assert value["bazaar_indexing_status"] == "INDETERMINATE"
    assert value["bazaar_indexing_confirmed"] is False
    assert value["bazaar_discovery_reference"] is None
    assert descriptor()["discovery"]["bazaar_metadata_declared"] is True


def test_provider_metadata_is_bounded_ascii_without_payment_changes():
    before = x402._requirements()
    body = TestClient(app).post("/v1/public/ask", json={"query": "offline"}).json()
    assert body["resource"]["serviceName"] == "PRAMA-Dynamagh"
    tags = body["resource"]["tags"]
    assert len(tags) <= 5 and all(0 < len(t) <= 32 and t.isascii() and t.isprintable() for t in tags)
    assert body["accepts"] == [before]


def test_public_labels_and_documentary_proofs_are_sanitized():
    import os
    from pathlib import Path
    root = Path(os.environ.get("PRAMA_REPO_ROOT", Path(__file__).resolve().parents[3]))
    page = (root / "frontend/public/adoption/index.html").read_text(encoding="utf-8")
    script = (root / "frontend/public/adoption/adoption.js").read_text(encoding="utf-8")
    assert "Consumer Results Delivered" in page and "Consumer Results Delivered" in script
    assert "Consumer Fulfilled" not in page + script
    note = (root / "docs/observations/TELEGRAPH_INTENT_FULFILLMENT_2026-09-26.md").read_text(encoding="utf-8")
    assert "742b0c6a-e962-43b5-99d6-74d45bc8cb70" in note
    assert "194f18e3-7a59-4490-a1fc-7a49d6a3dad8" in note
    assert "NOT_ESTABLISHED" in note and "NOT_AVAILABLE" in note
    for forbidden in ("result_capability:", "PAYMENT-SIGNATURE:", "Authorization:", "private_key:", "payer_wallet_address"):
        assert forbidden not in note
