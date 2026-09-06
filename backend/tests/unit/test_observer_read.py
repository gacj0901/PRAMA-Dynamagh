from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
PATH = "/v1/operator/o-evidence/provenance/status"


def test_observer_read_auth_fails_closed(monkeypatch):
    monkeypatch.setenv("PRAMA_OBSERVER_READ_TOKEN", "observer-test-token")
    assert client.get(PATH).status_code == 401
    assert client.get(PATH, headers={"Authorization": "Bearer wrong-token"}).status_code == 401

    monkeypatch.delenv("PRAMA_OBSERVER_READ_TOKEN")
    assert client.get(PATH).status_code == 503


def test_observer_read_valid_token_returns_bounded_status(monkeypatch):
    monkeypatch.setenv("PRAMA_OBSERVER_READ_TOKEN", "observer-test-token")
    monkeypatch.setattr(
        "app.api.observer._status_snapshot",
        lambda session: {
            "observer_version": "0.1",
            "eligible_evidence_count": 0,
            "warmup_count": 0,
            "kernel_evaluated_count": 0,
            "omega_0_count": 0,
            "omega_1_count": 0,
            "context_count": 0,
            "contexts": [],
            "latest_gamma": None,
            "replay_checked_count": 0,
            "replay_match_count": 0,
            "deterministic_hash_match": True,
            "shadow_mode": True,
            "decision_gate_unchanged": True,
        },
    )
    response = client.get(PATH, headers={"Authorization": "Bearer observer-test-token"})
    assert response.status_code == 200
    assert response.json()["deterministic_hash_match"] is True
    assert response.json()["shadow_mode"] is True
