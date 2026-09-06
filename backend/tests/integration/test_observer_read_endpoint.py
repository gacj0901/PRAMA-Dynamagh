from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.domain.mandates import Evidence, OEvidenceProvenanceObservation
from app.main import app
from app.persistence.database import get_session
from tests.integration.test_o_evidence_provenance import _chain, _observe, provenance_session


PATH = "/v1/operator/o-evidence/provenance/status"


def test_observer_read_is_read_only_and_reports_replay(provenance_session, monkeypatch):
    session, source_ids = provenance_session
    call_id = _chain(session, source_ids, when=datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc))
    _observe(session, call_id)
    before = (
        session.query(Evidence).count(),
        session.query(OEvidenceProvenanceObservation).count(),
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setenv("PRAMA_OBSERVER_READ_TOKEN", "observer-test-token")
    try:
        response = TestClient(app).get(PATH, headers={"Authorization": "Bearer observer-test-token"})
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_evidence_count"] == 1
    assert body["warmup_count"] == 1
    assert body["kernel_evaluated_count"] == 0
    assert body["replay_checked_count"] == 1
    assert body["replay_match_count"] == 1
    assert body["deterministic_hash_match"] is True
    assert body["shadow_mode"] is True
    assert body["decision_gate_unchanged"] is True
    assert body["contexts"][0]["intent"] == "CRYPTO_PRICE"
    assert "miner-a" not in str(body["contexts"])
    assert (
        session.query(Evidence).count(),
        session.query(OEvidenceProvenanceObservation).count(),
    ) == before
