"""PostgreSQL persistence and non-interference gate for E1-P."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.mandates import (
    AutonomyPolicy,
    AutonomyRun,
    CryptoPriceEvidence,
    Decision,
    EpistemicEvaluation,
    EpistemicTarget,
    Evidence,
    EvidenceRelation,
    EvidenceRequirement,
    Mandate,
    OEvidenceProvenanceContextState,
    OEvidenceProvenanceContract,
    OEvidenceProvenanceGlobalState,
    OEvidenceProvenanceObservation,
    PublicManualSpendLedger,
    PublicManualSpendReservation,
    StructuralEvaluation,
    Ticket,
)
from app.epistemic.contracts import (
    build_crypto_price_evidence,
    build_crypto_price_target,
    build_evidence_requirement,
    canonical_hash,
)
from app.epistemic.evaluator import evaluate_crypto_price, persist_e1_evaluation, replay_crypto_price


UTC = timezone.utc


def _snapshot_existing(session: Session, excluded_ids: set[str]):
    models = (
        Evidence,
        StructuralEvaluation,
        Decision,
        Ticket,
        OEvidenceProvenanceContract,
        OEvidenceProvenanceGlobalState,
        OEvidenceProvenanceContextState,
        OEvidenceProvenanceObservation,
        AutonomyPolicy,
        AutonomyRun,
        PublicManualSpendLedger,
        PublicManualSpendReservation,
    )
    snapshot = {}
    for model in models:
        rows = session.scalars(select(model)).all()
        retained = []
        for row in rows:
            identity_values = {
                str(getattr(row, name))
                for name in ("mandate_id", "evidence_id", "target_id", "evaluation_id", "decision_id", "ticket_id")
                if hasattr(row, name) and getattr(row, name) is not None
            }
            if identity_values & excluded_ids:
                continue
            retained.append(tuple(getattr(row, column.name) for column in model.__table__.columns))
        snapshot[model.__tablename__] = tuple(sorted(retained, key=repr))
    return snapshot


def test_e1p_persistence_replay_and_non_interference():
    engine = create_engine(os.environ["DATABASE_URL"])
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session: Session = session_factory()
    mandate_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    typed_id = str(uuid.uuid4())
    requirement_ids = [str(uuid.uuid4()) for _ in range(4)]
    excluded_ids = {mandate_id, evidence_id, target_id}
    try:
        mandate = Mandate(
            mandate_id=mandate_id,
            actor_id="e1p-postgres-fixture",
            text="E1-P persisted fixture",
            mandate_type="CRYPTO_PRICE",
            constraints={},
            max_budget_usdc=Decimal("0"),
            status="RECEIVED",
            origin="MANUAL",
        )
        evidence = Evidence(
            evidence_id=evidence_id,
            mandate_id=mandate_id,
            evidence_type="TELEGRAPH_RESULT",
            source_kind="TELEGRAPH",
            source_intent="CRYPTO_PRICE",
            source_miner_id="fixture-miner",
            source_signal_hash="0xfixture-signal",
            normalized_payload={"fixture": "e1p"},
            content_hash=canonical_hash({"fixture": "e1p"}),
            normalizer_version="telegraph-evidence-v0",
            provenance_status="VERIFIED",
            admissibility="ADMITTED",
            limitation_codes=[],
        )
        session.add_all([mandate, evidence])
        session.commit()
        before = _snapshot_existing(session, excluded_ids)

        target = build_crypto_price_target(
            mandate_id=mandate_id,
            target_id=target_id,
            asset="BTC",
            quote_currency="USD",
            as_of=datetime(2026, 9, 6, 12, tzinfo=UTC),
        )
        requirements = [
            build_evidence_requirement(
                target_id=target_id,
                requirement_id=requirement_id,
                requirement_type=requirement_type,
                parameters={"max_age_seconds": 300} if requirement_type == "temporal_applicability" else {},
            )
            for requirement_id, requirement_type in zip(
                requirement_ids,
                ("asset_identity", "quote_currency", "price_value", "temporal_applicability"),
                strict=True,
            )
        ]
        typed = build_crypto_price_evidence(
            evidence_id=evidence_id,
            crypto_price_evidence_id=typed_id,
            asset="BTC",
            quote_currency="USD",
            price_value="50000",
            observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        )
        session.add(target)
        session.add_all(requirements)
        session.add(typed)
        session.commit()

        result = evaluate_crypto_price(
            target=target,
            requirements=requirements,
            evidence=[evidence],
            typed_evidence_by_id={evidence_id: typed},
        )
        persist_e1_evaluation(session, result)
        session.commit()
        replay = replay_crypto_price(
            target=target,
            requirements=requirements,
            evidence=[evidence],
            typed_evidence_by_id={evidence_id: typed},
        )
        stored = session.get(EpistemicEvaluation, result.evaluation.evaluation_id)
        assert stored is not None
        assert stored.canonical_hash == replay.evaluation.canonical_hash
        assert stored.evidence_set_hash == replay.evaluation.evidence_set_hash
        assert stored.requirement_states == replay.evaluation.requirement_states
        assert stored.relations == replay.evaluation.relations
        assert stored.structural_state == "COMPLETE"
        assert _snapshot_existing(session, excluded_ids) == before
    finally:
        session.rollback()
        session.query(EpistemicEvaluation).filter_by(target_id=target_id).delete()
        session.query(EvidenceRelation).filter_by(target_id=target_id).delete()
        session.query(CryptoPriceEvidence).filter_by(evidence_id=evidence_id).delete()
        session.query(EvidenceRequirement).filter_by(target_id=target_id).delete()
        session.query(EpistemicTarget).filter_by(target_id=target_id).delete()
        session.query(Evidence).filter_by(evidence_id=evidence_id).delete()
        session.query(Mandate).filter_by(mandate_id=mandate_id).delete()
        session.commit()
        session.close()
        engine.dispose()
