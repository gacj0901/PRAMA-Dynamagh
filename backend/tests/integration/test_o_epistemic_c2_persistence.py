"""PostgreSQL persistence and non-interference tests for E1-C2."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.mandates import (
    CryptoPriceEvidence,
    Decision,
    EpistemicEvaluation,
    EpistemicTarget,
    Evidence,
    EvidenceRelation,
    EvidenceRequirement,
    Mandate,
    StructuralEvaluation,
    Ticket,
)
from app.epistemic.contracts import (
    build_crypto_price_evidence,
    build_crypto_price_target,
    build_evidence_requirement,
)
from app.epistemic.evaluator import evaluate_crypto_price, persist_e1_evaluation, replay_crypto_price
from app.pramagraph.evaluation import digest


UTC = timezone.utc


@pytest.fixture
def c2_session():
    db_engine = create_engine(os.environ["DATABASE_URL"])
    session_factory = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session: Session = session_factory()
    mandate_id = str(uuid.uuid4())
    evidence_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    target_id = str(uuid.uuid4())
    requirement_ids = [str(uuid.uuid4()) for _ in range(4)]
    typed_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    try:
        mandate = Mandate(
            mandate_id=mandate_id,
            actor_id="e1-c2-test",
            text="typed CRYPTO_PRICE fixture",
            mandate_type="CRYPTO_PRICE",
            constraints={},
            max_budget_usdc=Decimal("0"),
            status="RECEIVED",
            origin="MANUAL",
        )
        evidence = [
            Evidence(
                evidence_id=evidence_ids[0],
                mandate_id=mandate_id,
                evidence_type="TELEGRAPH_RESULT",
                source_kind="TELEGRAPH",
                source_intent="CRYPTO_PRICE",
                source_miner_id="miner-1",
                source_signal_hash="0xsignal-1",
                normalized_payload={"fixture": "usd"},
                content_hash=digest({"fixture": "usd"}),
                normalizer_version="telegraph-evidence-v0",
                provenance_status="VERIFIED",
                admissibility="ADMITTED",
                limitation_codes=[],
            ),
            Evidence(
                evidence_id=evidence_ids[1],
                mandate_id=mandate_id,
                evidence_type="TELEGRAPH_RESULT",
                source_kind="TELEGRAPH",
                source_intent="CRYPTO_PRICE",
                source_miner_id="miner-2",
                source_signal_hash="0xsignal-2",
                normalized_payload={"fixture": "eur"},
                content_hash=digest({"fixture": "eur"}),
                normalizer_version="telegraph-evidence-v0",
                provenance_status="VERIFIED",
                admissibility="LIMITED",
                limitation_codes=["UPSTREAM_WARNING"],
            ),
        ]
        session.add(mandate)
        session.add_all(evidence)
        session.commit()
        yield session, {
            "mandate_id": mandate_id,
            "evidence": evidence,
            "evidence_ids": evidence_ids,
            "target_id": target_id,
            "requirement_ids": requirement_ids,
            "typed_ids": typed_ids,
        }
    finally:
        session.rollback()
        session.query(EpistemicEvaluation).filter_by(target_id=target_id).delete()
        session.query(EvidenceRelation).filter_by(target_id=target_id).delete()
        session.query(CryptoPriceEvidence).filter(CryptoPriceEvidence.evidence_id.in_(evidence_ids)).delete(
            synchronize_session=False
        )
        session.query(EvidenceRequirement).filter_by(target_id=target_id).delete()
        session.query(EpistemicTarget).filter_by(target_id=target_id).delete()
        session.query(Evidence).filter(Evidence.evidence_id.in_(evidence_ids)).delete(synchronize_session=False)
        session.query(Mandate).filter_by(mandate_id=mandate_id).delete()
        session.commit()
        session.close()
        db_engine.dispose()


def _persist_fixture_contracts(session: Session, ids: dict[str, object]):
    target = build_crypto_price_target(
        mandate_id=str(ids["mandate_id"]),
        target_id=str(ids["target_id"]),
        asset="BTC",
        quote_currency="USD",
        as_of=datetime(2026, 9, 6, 12, tzinfo=UTC),
    )
    requirements = [
        build_evidence_requirement(
            target_id=target.target_id,
            requirement_id=requirement_id,
            requirement_type=requirement_type,
            parameters={"max_age_seconds": 300} if requirement_type == "temporal_applicability" else {},
        )
        for requirement_id, requirement_type in zip(
            ids["requirement_ids"],
            ("asset_identity", "quote_currency", "price_value", "temporal_applicability"),
            strict=True,
        )
    ]
    typed = [
        build_crypto_price_evidence(
            evidence_id=str(ids["evidence_ids"][0]),
            crypto_price_evidence_id=str(ids["typed_ids"][0]),
            asset="BTC",
            quote_currency="USD",
            price_value="50000",
            observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        ),
        build_crypto_price_evidence(
            evidence_id=str(ids["evidence_ids"][1]),
            crypto_price_evidence_id=str(ids["typed_ids"][1]),
            asset="BTC",
            quote_currency="EUR",
            price_value="47000",
            observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        ),
    ]
    session.add(target)
    session.add_all(requirements)
    session.add_all(typed)
    session.commit()
    return target, requirements, typed


def _legacy_snapshot(session: Session):
    return {
        "evidence": [
            (row.evidence_id, row.content_hash, row.normalized_payload, row.admissibility)
            for row in session.scalars(select(Evidence).order_by(Evidence.evidence_id))
        ],
        "evaluations": [
            (row.evaluation_id, row.evidence_set_hash, row.structural_state, row.evaluation_payload)
            for row in session.scalars(select(StructuralEvaluation).order_by(StructuralEvaluation.evaluation_id))
        ],
        "decisions": [
            (row.decision_id, row.evidence_set_hash, row.state, row.reason_codes, row.decision_payload)
            for row in session.scalars(select(Decision).order_by(Decision.decision_id))
        ],
        "tickets": [
            (row.ticket_id, row.ticket_hash, row.canonical_payload, row.anchor_status)
            for row in session.scalars(select(Ticket).order_by(Ticket.ticket_id))
        ],
    }


def test_c2_persists_relations_evaluation_and_preserves_legacy_artifacts(c2_session):
    session, ids = c2_session
    legacy_before = _legacy_snapshot(session)
    target, requirements, typed = _persist_fixture_contracts(session, ids)
    typed_by_id = {item.evidence_id: item for item in typed}
    result = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=ids["evidence"],
        typed_evidence_by_id=typed_by_id,
    )
    persisted = persist_e1_evaluation(session, result)
    session.commit()
    assert persisted.structural_state == "CONTRADICTED"
    assert session.scalar(select(func.count()).select_from(EvidenceRelation).where(EvidenceRelation.target_id == target.target_id)) == 8
    assert session.scalar(select(func.count()).select_from(EpistemicEvaluation).where(EpistemicEvaluation.target_id == target.target_id)) == 1
    assert session.scalar(select(func.count()).select_from(EvidenceRelation).where(EvidenceRelation.relation_state == "SATISFIES")) >= 1
    assert session.scalar(select(func.count()).select_from(EvidenceRelation).where(EvidenceRelation.relation_state == "CONTRADICTS")) >= 1
    assert _legacy_snapshot(session) == legacy_before


@pytest.mark.parametrize("model_name", ["relation", "evaluation"])
def test_c2_rows_are_database_immutable(c2_session, model_name):
    session, ids = c2_session
    target, requirements, typed = _persist_fixture_contracts(session, ids)
    result = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=ids["evidence"],
        typed_evidence_by_id={item.evidence_id: item for item in typed},
    )
    persist_e1_evaluation(session, result)
    session.commit()
    if model_name == "relation":
        row = session.query(EvidenceRelation).filter_by(target_id=target.target_id).first()
        row.relation_basis = {"rule": "mutated"}
    else:
        row = session.query(EpistemicEvaluation).filter_by(target_id=target.target_id).one()
        row.limitations = ["mutated"]
    with pytest.raises(DBAPIError):
        session.commit()
    session.rollback()


def test_c2_relation_lineage_is_unique(c2_session):
    session, ids = c2_session
    target, requirements, typed = _persist_fixture_contracts(session, ids)
    result = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=ids["evidence"],
        typed_evidence_by_id={item.evidence_id: item for item in typed},
    )
    persist_e1_evaluation(session, result)
    session.commit()
    duplicate = EvidenceRelation(
        relation_id=str(uuid.uuid4()),
        target_id=result.relations[0].target_id,
        requirement_id=result.relations[0].requirement_id,
        evidence_id=result.relations[0].evidence_id,
        relation_state=result.relations[0].relation_state,
        relation_basis=result.relations[0].relation_basis,
        observer_version=result.relations[0].observer_version,
        contract_version=result.relations[0].contract_version,
        canonical_hash=result.relations[0].canonical_hash,
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_c2_replay_roundtrip_is_exact(c2_session):
    session, ids = c2_session
    target, requirements, typed = _persist_fixture_contracts(session, ids)
    typed_by_id = {item.evidence_id: item for item in typed}
    result = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=ids["evidence"],
        typed_evidence_by_id=typed_by_id,
    )
    persist_e1_evaluation(session, result)
    session.commit()
    replay = replay_crypto_price(
        target=target,
        requirements=list(reversed(requirements)),
        evidence=list(reversed(ids["evidence"])),
        typed_evidence_by_id=typed_by_id,
    )
    stored = session.query(EpistemicEvaluation).filter_by(evaluation_id=result.evaluation.evaluation_id).one()
    assert stored.canonical_hash == replay.evaluation.canonical_hash
    assert stored.evidence_set_hash == replay.evaluation.evidence_set_hash
    assert stored.requirement_states == replay.evaluation.requirement_states
    assert stored.relations == replay.evaluation.relations
