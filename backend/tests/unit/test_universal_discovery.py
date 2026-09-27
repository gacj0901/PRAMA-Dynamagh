import json
from fastapi.testclient import TestClient

from app.main import app


def test_universal_discovery_public_cacheable_and_canonical():
    response = TestClient(app).get("/v1/public/discovery")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=300"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    value = response.json()
    assert value["schema_version"] == "prama.discovery.v1"
    assert value["execution"] == {
        "method": "POST",
        "endpoint": "https://prama-dynamagh.up.railway.app/v1/public/ask",
        "asynchronous": True,
    }
    assert value["capabilities"]["url"].endswith("/v1/public/capabilities")
    assert TestClient(app).get("/v1/public/capabilities").json()["canonical_discovery_url"] == "https://prama-dynamagh.up.railway.app/v1/public/discovery"
    assert value["mcp"]["endpoint"].endswith("/mcp")
    assert value["agent_manifest"]["url"].endswith("/.well-known/prama-agent.json")
    assert value["machine_documentation"]["agent_guide"].endswith("/agents.md")
    assert value["machine_documentation"]["llms"].endswith("/llms.txt")


def test_universal_discovery_does_not_contact_provider_or_database(monkeypatch):
    import socket
    from sqlalchemy.orm import Session

    original_connect = socket.socket.connect

    def forbidden(self, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(self, address)
        raise AssertionError("Discovery must not contact providers or a database")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(Session, "execute", forbidden)
    response = TestClient(app).get("/v1/public/discovery")
    assert response.status_code == 200


def test_universal_discovery_payment_bazaar_and_safety_contract():
    value = TestClient(app).get("/v1/public/discovery").json()
    assert value["service"]["environment"] == "TESTNET"
    assert value["payment"] == {
        "protocol": "x402", "version": 2, "scheme": "exact",
        "network": "eip155:84532", "network_name": "Base Sepolia", "environment": "TESTNET",
        "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", "asset_symbol": "USDC",
        "asset_decimals": 6, "amount_atomic": 10000, "amount_display": "0.01 USDC",
        "payTo": "0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6",
        "terms_source": "Validate the live HTTP 402 challenge before any payment.",
    }
    assert value["facilitator"]["provider"] == "PayAI"
    assert "result_capability" not in json.dumps(value)
    assert "payer_wallet" not in json.dumps(value).lower()
    assert "payment_signature" not in json.dumps(value).lower()
    assert value["bazaar"]["metadata_declared"] is True
    assert value["bazaar"]["indexing_confirmed"] is True
    assert value["bazaar"]["metadata_refresh"] in {"CURRENT", "PENDING", "UNKNOWN"}
    assert value["semantics"]["external_m2m_demand_from_listings"] == "NOT_INFERRED"
    assert value["semantics"]["adoption_metric"] == "Consumer Results Delivered"


def test_universal_discovery_telegraph_range_and_nuanced_observations():
    value = TestClient(app).get("/v1/public/discovery").json()
    assert value["telegraph"]["intent_resolution_owner"] == "Telegraph"
    assert value["telegraph"]["miner_selection_owner"] == "Telegraph"
    assert value["telegraph"]["requested_intent_semantics"] == "application-level semantic hint"
    assert value["telegraph"]["explicit_telegraph_intent_id_required"] is False
    assert value["telegraph"]["local_telegraph_intent_registry"] is False
    observations = {row["requested_intent"]: row for row in value["observed_request_capabilities"]}
    assert len(observations) == 5
    assert "WEB_SEARCH" in observations and "FINANCIAL_DATA" in observations
    assert observations["WEATHER_FORECAST"]["state"] == "UNVERIFIED"
    assert observations["RESEARCH_QUERY"]["external_status"] == "UNDER_INVESTIGATION"
    token_holder = observations["TOKEN_HOLDER_COUNT"]
    assert token_holder["acquisition"] == "SUCCEEDED"
    assert token_holder["evidence"] == "ADMITTED"
    assert token_holder["provenance"] == "VERIFIED"
    assert token_holder["decision"] == "PERMIT"
    assert token_holder["delivery"] == "NOT_AVAILABLE"
    assert token_holder["observed_state"] == "OBSERVED_ACQUISITION_SUCCESS_RESULT_NOT_AVAILABLE"
    assert "5dba61f6" not in json.dumps(value)
    assert len(value["intelligence_domains"]) > 1


def test_universal_discovery_preserves_async_result_and_semantic_invariants():
    value = TestClient(app).get("/v1/public/discovery").json()
    contract = value["async_result_contract"]
    assert contract["capability_is_secret"] is True
    assert contract["capability_in_discovery"] is False
    assert any("HTTP 402" in step for step in contract["steps"])
    assert any("HTTP 202" in step for step in contract["steps"])
    assert any("X-PRAMA-Result-Capability" in step for step in contract["steps"])
    semantics = value["semantics"]
    assert semantics["payment_is_authority"] is False
    assert semantics["acquisition_success_is_delivery"] is False
    assert semantics["delivered_implies_semantic_task_fulfillment"] is False
    assert semantics["evidence_admitted_implies_mandate_satisfied"] is False
    assert semantics["decision_permit_implies_semantic_fulfillment"] is False
    assert "Consumer Fulfilled" not in json.dumps(value)
