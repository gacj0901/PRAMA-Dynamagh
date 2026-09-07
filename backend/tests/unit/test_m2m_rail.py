from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_m2m_auth_is_dedicated_and_fail_closed(monkeypatch):
    monkeypatch.delenv("PRAMA_M2M_API_TOKEN", raising=False)
    assert client.get("/v1/m2m/mandates/unknown").status_code == 503

    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", "m2m-test-token")
    assert client.get("/v1/m2m/mandates/unknown").status_code == 401
    assert client.get("/v1/m2m/mandates/unknown", headers={"Authorization": "Bearer internal-token"}).status_code == 401


def test_m2m_creation_requires_idempotency_and_rejects_capability_fields(monkeypatch):
    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", "m2m-test-token")
    headers = {"Authorization": "Bearer m2m-test-token"}
    missing = client.post(
        "/v1/m2m/mandates",
        headers=headers,
        json={"agent_id": "agent", "client_id": "client", "text": "bounded query"},
    )
    assert missing.status_code == 400

    forbidden = client.post(
        "/v1/m2m/mandates",
        headers={**headers, "Idempotency-Key": "m2m-unit-forbidden"},
        json={
            "agent_id": "agent",
            "client_id": "client",
            "text": "bounded query",
            "calldata": "0xdeadbeef",
            "miner_id": "arbitrary-miner",
        },
    )
    assert forbidden.status_code == 422


def test_m2m_rail_has_no_forbidden_capability_routes():
    paths = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if path.startswith("/v1/m2m")
    }
    assert paths == {
        ("/v1/m2m/mandates", "POST"),
        ("/v1/m2m/mandates/{mandate_id}", "GET"),
        ("/v1/m2m/tickets/{ticket_id}", "GET"),
        ("/v1/m2m/titular-check/presented", "POST"),
    }
    for path, method in (
        ("/v1/m2m/gateway", "POST"),
        ("/v1/m2m/signer", "GET"),
        ("/v1/m2m/mandates/unknown/anchor", "POST"),
        ("/v1/m2m/erc8183/jobs", "POST"),
        ("/v1/m2m/autonomy/policies", "PATCH"),
    ):
        response = client.request(method, path, headers={"Authorization": "Bearer m2m-test-token"})
        assert response.status_code == 404
