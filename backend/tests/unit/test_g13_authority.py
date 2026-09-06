from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.agents.identity import get_or_create_m2m_identity
from app.api.m2m import _m2m_context_id
from app.domain.mandates import AgentIdentity
from app.main import app


class MemorySession:
    def __init__(self):
        self.rows = {}

    def get(self, model, key):
        return self.rows.get(key)

    def add(self, value):
        self.rows[value.agent_id] = value

    def flush(self):
        return None


def test_m2m_context_is_deterministic_and_secret_free():
    first = _m2m_context_id("token-a")
    assert first == _m2m_context_id("token-a")
    assert first != _m2m_context_id("token-b")
    assert "token-a" not in first
    assert first.startswith("m2m-token-sha256:")


def test_m2m_identity_is_scoped_to_authenticated_context():
    session = MemorySession()
    identity = get_or_create_m2m_identity(session, "agent-1", "m2m-token-sha256:a")
    assert identity.m2m_context_id == "m2m-token-sha256:a"
    assert get_or_create_m2m_identity(session, "agent-1", "m2m-token-sha256:a") is identity
    try:
        get_or_create_m2m_identity(session, "agent-1", "m2m-token-sha256:b")
    except ValueError as error:
        assert str(error) == "M2M_AGENT_CONTEXT_CONFLICT"
    else:
        raise AssertionError("an identity must not cross authenticated M2M contexts")


def test_m2m_cannot_claim_internal_identity_or_foreign_mandate_scope():
    session = MemorySession()
    session.add(AgentIdentity(agent_id="autonomy-controller", name="internal", origin="INTERNAL_AUTONOMY"))
    try:
        get_or_create_m2m_identity(session, "autonomy-controller", "m2m-token-sha256:a")
    except ValueError as error:
        assert str(error) == "M2M_AGENT_ID_ORIGIN_CONFLICT"
    else:
        raise AssertionError("external M2M must not claim the internal autonomy identity")

    from app.api.m2m import _get_m2m_mandate

    class MandateSession:
        def get(self, _model, _key):
            return type("M", (), {"origin": "M2M", "m2m_context_id": "m2m-token-sha256:a"})()

    try:
        _get_m2m_mandate(MandateSession(), "mandate-1", "m2m-token-sha256:b")
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("M2M reads must be scoped to the authenticated context")


def test_identity_schema_has_no_authority_material_and_external_internal_creation_is_blocked(monkeypatch):
    assert {"private_key", "signer", "gateway", "calldata"}.isdisjoint(AgentIdentity.__table__.columns.keys())
    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", "g13-test-token")
    response = TestClient(app).post(
        "/v1/agent-identities",
        json={"agent_id": "internal-spoof", "name": "spoof", "origin": "INTERNAL_AUTONOMY"},
        headers={"Authorization": "Bearer g13-test-token"},
    )
    assert response.status_code == 422
