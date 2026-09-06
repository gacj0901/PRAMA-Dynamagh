"""PostgreSQL validation of O_EVIDENCE_PROVENANCE v0.1 without paid traffic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import uuid

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import Session, sessionmaker

from app.domain.mandates import (
    AcquisitionStatus,
    AcquisitionTask,
    Evidence,
    Mandate,
    OEvidenceProvenanceContextState,
    OEvidenceProvenanceGlobalState,
    OEvidenceProvenanceObservation,
    TelegraphCall,
)
from app.observers.provenance import (
    OBSERVER_ID,
    observe_telegraph_call,
    replay_provenance,
)
from app.pramagraph.evaluation import digest


@pytest.fixture
def provenance_session():
    engine = create_engine(os.environ["DATABASE_URL"])
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    source_ids: list[tuple[str, str, str, str]] = []
    try:
        session.execute(delete(OEvidenceProvenanceObservation))
        session.execute(delete(OEvidenceProvenanceContextState))
        session.execute(text("UPDATE o_evidence_provenance_global_states SET observation_count=0, omega_sum=0, next_sequence=1, last_observed_at=NULL WHERE observer_id=:id"), {"id": OBSERVER_ID})
        session.commit()
        yield session, source_ids
    finally:
        session.rollback()
        session.execute(delete(OEvidenceProvenanceObservation))
        session.execute(delete(OEvidenceProvenanceContextState))
        session.execute(text("UPDATE o_evidence_provenance_global_states SET observation_count=0, omega_sum=0, next_sequence=1, last_observed_at=NULL WHERE observer_id=:id"), {"id": OBSERVER_ID})
        for mandate_id, acquisition_id, call_id, evidence_id in source_ids:
            session.execute(delete(Evidence).where(Evidence.evidence_id == evidence_id))
            session.execute(delete(TelegraphCall).where(TelegraphCall.telegraph_call_id == call_id))
            session.execute(delete(AcquisitionTask).where(AcquisitionTask.acquisition_id == acquisition_id))
            session.execute(delete(Mandate).where(Mandate.mandate_id == mandate_id))
        session.commit()
        session.close()
        engine.dispose()


def _chain(
    session: Session,
    source_ids: list,
    *,
    when: datetime,
    miner_id: str = "miner-a",
    intent: str = "CRYPTO_PRICE",
    omega_break: str | None = None,
    include_evidence: bool = True,
) -> str:
    suffix = str(uuid.uuid4())
    mandate_id = str(uuid.uuid4())
    acquisition_id = str(uuid.uuid4())
    call_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    source_ids.append((mandate_id, acquisition_id, call_id, evidence_id))
    mandate = Mandate(
        mandate_id=mandate_id,
        actor_id="provenance-test-" + suffix,
        text="offline provenance test",
        mandate_type=intent,
        constraints={},
        max_budget_usdc=Decimal("0"),
        status="TICKETED",
        origin="MANUAL",
        created_at=when,
    )
    task_mandate_id = mandate_id
    task = AcquisitionTask(
        acquisition_id=acquisition_id,
        mandate_id=task_mandate_id,
        query="offline provenance test",
        requested_intent=intent,
        required=True,
        status=AcquisitionStatus.SUCCEEDED.value,
        ordinal=0,
        attempt_count=1,
        completed_at=when + timedelta(seconds=1),
        created_at=when,
    )
    signal_hash = "0x" + "ab" * 32
    call = TelegraphCall(
        telegraph_call_id=call_id,
        mandate_id=mandate_id,
        acquisition_id=acquisition_id,
        causal_request_id=str(uuid.uuid4()),
        miner_id=miner_id,
        intent=intent,
        signal_hash=signal_hash,
        raw_response={"result": "offline"},
        warnings=[],
        status="SUCCEEDED",
        created_at=when + timedelta(seconds=2),
        completed_at=when + timedelta(seconds=3),
    )
    session.add(mandate)
    session.flush()
    session.add(task)
    session.flush()
    session.add(call)
    session.flush()
    if include_evidence:
        evidence_mandate = mandate_id
        evidence_acquisition = acquisition_id
        evidence_call = call_id
        evidence_intent = intent
        evidence_miner = miner_id
        evidence_signal = signal_hash
        if omega_break == "evidence_mandate":
            evidence_mandate = str(uuid.uuid4())
        elif omega_break == "evidence_acquisition":
            evidence_acquisition = str(uuid.uuid4())
        elif omega_break == "evidence_call":
            evidence_call = str(uuid.uuid4())
        elif omega_break == "source_intent":
            evidence_intent = "OTHER"
        elif omega_break == "source_miner":
            evidence_miner = "other-miner"
        elif omega_break == "source_signal":
            evidence_signal = "0x" + "cd" * 32
        session.add(Evidence(
            evidence_id=evidence_id,
            mandate_id=evidence_mandate,
            acquisition_id=evidence_acquisition,
            telegraph_call_id=evidence_call,
            evidence_type="TELEGRAPH_RESULT",
            source_kind="TELEGRAPH",
            source_intent=evidence_intent,
            source_miner_id=evidence_miner,
            source_signal_hash=evidence_signal,
            normalized_payload={"offline": True},
            content_hash=digest({"offline": True}),
            normalizer_version="test-v0",
            provenance_status="VERIFIED",
            admissibility="ADMITTED",
            limitation_codes=[],
        ))
    session.flush()
    return call_id


def _observe(session: Session, call_id: str) -> dict:
    result = observe_telegraph_call(session, call_id)
    session.commit()
    return result


def test_intact_lineage_and_replay_are_deterministic(provenance_session):
    session, ids = provenance_session
    when = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
    first = _chain(session, ids, when=when)
    assert _observe(session, first)["omega"] == 0
    second = _chain(session, ids, when=when + timedelta(minutes=1))
    assert _observe(session, second)["support_status"] == "WARMUP"
    third = _chain(session, ids, when=when + timedelta(minutes=2))
    result = _observe(session, third)
    assert result["support_status"] == "CONTEXT_MEAN"
    assert result["expected"] == 0.0
    assert result["kernel_output"] is not None
    replay = replay_provenance(session)
    assert replay["status"] == "VALID"
    assert replay["observation_count"] == 3


@pytest.mark.parametrize("broken", ["evidence_mandate", "evidence_acquisition", "evidence_call", "source_intent", "source_miner", "source_signal"])
def test_each_required_evidence_invariant_discontinuity_is_one(provenance_session, broken):
    session, ids = provenance_session
    call_id = _chain(session, ids, when=datetime(2026, 9, 6, 11, 0, tzinfo=timezone.utc), omega_break=broken)
    assert _observe(session, call_id)["omega"] == 1


def test_missing_evidence_parent_is_discontinuity(provenance_session):
    session, ids = provenance_session
    call_id = _chain(session, ids, when=datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc), include_evidence=False)
    assert _observe(session, call_id)["omega"] == 1


def test_global_fallback_context_isolation_and_no_lookahead(provenance_session):
    session, ids = provenance_session
    base = datetime(2026, 9, 6, 13, 0, tzinfo=timezone.utc)
    assert _observe(session, _chain(session, ids, when=base, miner_id="a"))["support_status"] == "WARMUP"
    assert _observe(session, _chain(session, ids, when=base + timedelta(minutes=1), miner_id="b"))["support_status"] == "WARMUP"
    global_row = _observe(session, _chain(session, ids, when=base + timedelta(minutes=2), miner_id="c"))
    assert global_row["support_status"] == "GLOBAL_MEAN"
    assert global_row["expected"] == 0.0
    isolated = _observe(session, _chain(session, ids, when=base + timedelta(minutes=3), miner_id="a"))
    assert isolated["support_status"] == "GLOBAL_MEAN"
    assert isolated["expected"] == 0.0


def test_idempotency_ordering_and_gate_separation(provenance_session):
    session, ids = provenance_session
    base = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)
    evaluations_before = session.execute(text("SELECT COUNT(*) FROM structural_evaluations")).scalar_one()
    call_id = _chain(session, ids, when=base)
    first = _observe(session, call_id)
    assert _observe(session, call_id)["status"] == "ALREADY_RECORDED"
    old_call = _chain(session, ids, when=base - timedelta(minutes=1))
    assert observe_telegraph_call(session, old_call)["status"] == "OUT_OF_ORDER"
    session.rollback()
    assert session.query(OEvidenceProvenanceObservation).count() == 1
    assert session.execute(text("SELECT COUNT(*) FROM structural_evaluations")).scalar_one() == evaluations_before
