from datetime import datetime, timezone
import json

from fastapi.testclient import TestClient

from app.domain.mandates import (
    Decision,
    Evidence,
    OEvidenceProvenanceContextState,
    OEvidenceProvenanceContract,
    OEvidenceProvenanceGlobalState,
    OEvidenceProvenanceObservation,
    StructuralEvaluation,
    Ticket,
)
from app.main import app
from app.persistence.database import get_session
from tests.integration.test_o_evidence_provenance import _chain, _observe, provenance_session


PATH = "/v1/operator/o-evidence/provenance/status"
client = TestClient(app)


def _canonical(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _snapshot_rows(session, model, fields):
    return sorted(
        json.dumps(
            {field: _canonical(getattr(row, field)) for field in fields},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        for row in session.query(model).all()
    )


def _persistence_snapshot(session):
    return {
        "evidence": _snapshot_rows(
            session,
            Evidence,
            [
                "evidence_id",
                "mandate_id",
                "acquisition_id",
                "telegraph_call_id",
                "content_hash",
                "provenance_status",
                "admissibility",
                "normalized_payload",
            ],
        ),
        "evaluations": _snapshot_rows(
            session,
            StructuralEvaluation,
            [
                "evaluation_id",
                "mandate_id",
                "evidence_set_hash",
                "structural_state",
                "admitted_evidence_ids",
                "limited_evidence_ids",
                "rejected_evidence_ids",
                "evaluation_payload",
            ],
        ),
        "decisions": _snapshot_rows(
            session,
            Decision,
            [
                "decision_id",
                "mandate_id",
                "evaluation_id",
                "state",
                "evidence_set_hash",
                "reason_codes",
                "decision_payload",
            ],
        ),
        "tickets": _snapshot_rows(
            session,
            Ticket,
            [
                "ticket_id",
                "mandate_id",
                "decision_id",
                "canonical_payload",
                "ticket_hash",
                "anchor_status",
            ],
        ),
        "observer_contract": _snapshot_rows(
            session,
            OEvidenceProvenanceContract,
            ["observer_id", "observer_version", "kernel_config", "mode", "frozen_at"],
        ),
        "observer_global": _snapshot_rows(
            session,
            OEvidenceProvenanceGlobalState,
            ["observer_id", "observation_count", "omega_sum", "next_sequence", "last_observed_at"],
        ),
        "observer_context": _snapshot_rows(
            session,
            OEvidenceProvenanceContextState,
            ["observer_id", "miner_id", "intent", "observation_count", "omega_sum", "kernel_state", "last_observed_at"],
        ),
        "observer_rows": _snapshot_rows(
            session,
            OEvidenceProvenanceObservation,
            [
                "observation_id",
                "sequence",
                "mandate_id",
                "acquisition_id",
                "telegraph_call_id",
                "evidence_id",
                "omega",
                "expected",
                "support_status",
                "kernel_output",
                "observation_hash",
            ],
        ),
    }


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
    assert body["replay_checked_count"] is None
    assert body["replay_match_count"] is None
    assert body["deterministic_hash_match"] is None
    assert body["replay_verification_status"] == "NOT_PERSISTED"
    assert body["shadow_mode"] is True
    assert body["decision_gate_unchanged"] is True
    assert body["contexts"][0]["intent"] == "CRYPTO_PRICE"
    assert "miner-a" not in str(body["contexts"])
    assert (
        session.query(Evidence).count(),
        session.query(OEvidenceProvenanceObservation).count(),
    ) == before


def test_observer_status_is_noninterfering_and_does_not_replay(provenance_session, monkeypatch):
    session, source_ids = provenance_session
    base = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
    for index in range(3):
        _observe(session, _chain(session, source_ids, when=base.replace(minute=index), miner_id="miner-a"))

    before = _persistence_snapshot(session)
    persisted_gamma = session.query(OEvidenceProvenanceObservation).order_by(OEvidenceProvenanceObservation.sequence).all()[-1].kernel_output["row"]

    def forbidden(*args, **kwargs):
        raise AssertionError("operator status must not replay or execute KernelV3")

    monkeypatch.setattr("app.observers.provenance.KernelV3", forbidden)
    monkeypatch.setattr("app.observers.provenance.replay_provenance", forbidden)

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
    assert body["latest_gamma"] == persisted_gamma
    assert body["replay_verification_status"] == "NOT_PERSISTED"
    assert _persistence_snapshot(session) == before


def test_observer_read_token_cannot_reuse_protected_credentials(monkeypatch):
    for protected_name in ("PRAMA_M2M_API_TOKEN", "PRAMA_GATEWAY_INTERNAL_TOKEN", "TELEGRAPH_SIGNER_PRIVATE_KEY"):
        monkeypatch.setenv("PRAMA_OBSERVER_READ_TOKEN", "shared-value")
        monkeypatch.setenv(protected_name, "shared-value")
        assert client.get(PATH, headers={"Authorization": "Bearer shared-value"}).status_code == 503
        monkeypatch.delenv(protected_name)
