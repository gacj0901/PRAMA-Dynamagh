"""PostgreSQL-backed E1-C1 persistence tests without external traffic."""

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
    EpistemicTarget,
    Evidence,
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
from app.pramagraph.evaluation import digest


UTC = timezone.utc


@pytest.fixture
def epistemic_session():
    engine = create_engine(os.environ["DATABASE_URL"])
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session: Session = session_factory()
    mandate_id = str(uuid.uuid4())
    evidence_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    requirement_ids = [str(uuid.uuid4()) for _ in range(4)]
    typed_id = str(uuid.uuid4())
    try:
        mandate = Mandate(
            mandate_id=mandate_id,
            actor_id="e1-c1-test",
            text="typed CRYPTO_PRICE fixture",
            mandate_type="CRYPTO_PRICE",
            constraints={},
            max_budget_usdc=Decimal("0"),
            status="RECEIVED",
            origin="MANUAL",
        )
        evidence_payload = {"fixture": "e1-c1", "result": "not interpreted"}
        evidence = Evidence(
            evidence_id=evidence_id,
            mandate_id=mandate_id,
            acquisition_id=None,
            telegraph_call_id=None,
            evidence_type="TEST_TYPED_SOURCE",
            source_kind="TEST",
            source_intent="CRYPTO_PRICE",
            source_miner_id=None,
            source_signal_hash=None,
            normalized_payload=evidence_payload,
            content_hash=digest(evidence_payload),
            normalizer_version="e1-c1-test-v0",
            provenance_status="VERIFIED",
            admissibility="ADMITTED",
            limitation_codes=[],
        )
        session.add_all([mandate, evidence])
        session.commit()
        yield session, {
            "mandate_id": mandate_id,
            "evidence_id": evidence_id,
            "target_id": target_id,
            "requirement_ids": requirement_ids,
            "typed_id": typed_id,
        }
    finally:
        session.rollback()
        session.query(CryptoPriceEvidence).filter_by(crypto_price_evidence_id=typed_id).delete()
        session.query(EvidenceRequirement).filter(EvidenceRequirement.target_id == target_id).delete()
        session.query(EpistemicTarget).filter_by(target_id=target_id).delete()
        session.query(Evidence).filter_by(evidence_id=evidence_id).delete()
        session.query(Mandate).filter_by(mandate_id=mandate_id).delete()
        session.commit()
        session.close()
        engine.dispose()


def _persisted_contracts(session: Session, ids: dict[str, object]):
    target = build_crypto_price_target(
        mandate_id=str(ids["mandate_id"]),
        target_id=str(ids["target_id"]),
        asset="BTC",
        quote_currency="USD",
        as_of=datetime(2026, 9, 6, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
    )
    requirements = [
        build_evidence_requirement(
            target_id=target.target_id,
            requirement_id=requirement_id,
            requirement_type=requirement_type,
            parameters={"field": requirement_type},
            created_at=datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
        )
        for requirement_id, requirement_type in zip(
            ids["requirement_ids"],
            ("asset_identity", "quote_currency", "price_value", "temporal_applicability"),
            strict=True,
        )
    ]
    typed = build_crypto_price_evidence(
        evidence_id=str(ids["evidence_id"]),
        crypto_price_evidence_id=str(ids["typed_id"]),
        asset="BTC",
        quote_currency="USD",
        price_value=Decimal("50000.00"),
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        created_at=datetime(2026, 9, 6, 12, 1, tzinfo=UTC),
    )
    session.add(target)
    session.add_all(requirements)
    session.add(typed)
    session.commit()
    return target, requirements, typed


def test_e1_c1_persists_typed_contracts_and_preserves_existing_artifacts(epistemic_session):
    session, ids = epistemic_session
    evidence_before = session.get(Evidence, ids["evidence_id"])
    assert evidence_before is not None
    evidence_snapshot = {
        "content_hash": evidence_before.content_hash,
        "normalized_payload": evidence_before.normalized_payload,
        "admissibility": evidence_before.admissibility,
    }
    existing_gate_counts = (
        session.scalar(select(func.count()).select_from(StructuralEvaluation)),
        session.scalar(select(func.count()).select_from(Decision)),
        session.scalar(select(func.count()).select_from(Ticket)),
    )

    target, requirements, typed = _persisted_contracts(session, ids)
    session.expire_all()
    loaded_target = session.get(EpistemicTarget, target.target_id)
    loaded_typed = session.get(CryptoPriceEvidence, typed.crypto_price_evidence_id)
    assert loaded_target is not None
    assert loaded_target.canonical_hash == target.canonical_hash
    assert {item.requirement_type for item in session.scalars(select(EvidenceRequirement).where(EvidenceRequirement.target_id == target.target_id))} == {
        "asset_identity",
        "quote_currency",
        "price_value",
        "temporal_applicability",
    }
    assert loaded_typed is not None
    assert loaded_typed.evidence_id == ids["evidence_id"]
    assert loaded_typed.price_value == Decimal("50000.000000000000000000")

    evidence_after = session.get(Evidence, ids["evidence_id"])
    assert evidence_after is not None
    assert {
        "content_hash": evidence_after.content_hash,
        "normalized_payload": evidence_after.normalized_payload,
        "admissibility": evidence_after.admissibility,
    } == evidence_snapshot
    assert (
        session.scalar(select(func.count()).select_from(StructuralEvaluation)),
        session.scalar(select(func.count()).select_from(Decision)),
        session.scalar(select(func.count()).select_from(Ticket)),
    ) == existing_gate_counts


@pytest.mark.parametrize("model_name", ["target", "requirement", "typed"])
def test_e1_c1_rows_are_database_immutable(epistemic_session, model_name):
    session, ids = epistemic_session
    target, requirements, typed = _persisted_contracts(session, ids)
    if model_name == "target":
        target.parameters = {"asset": "ETH", "quote_currency": "USD", "as_of": None}
        target_id = target.target_id
    elif model_name == "requirement":
        requirements[0].parameters = {"field": "changed"}
        target_id = target.target_id
    else:
        typed.price_value = Decimal("1")
        target_id = typed.crypto_price_evidence_id
    with pytest.raises(DBAPIError):
        session.commit()
    session.rollback()
    if model_name == "target":
        assert session.get(EpistemicTarget, target_id).parameters["asset"] == "BTC"
    elif model_name == "requirement":
        assert session.scalars(select(EvidenceRequirement).where(EvidenceRequirement.target_id == target_id)).first().parameters == {"field": "asset_identity"}
    else:
        assert session.get(CryptoPriceEvidence, target_id).price_value == Decimal("50000.000000000000000000")


def test_e1_c1_enforces_one_typed_artifact_per_existing_evidence(epistemic_session):
    session, ids = epistemic_session
    _persisted_contracts(session, ids)
    duplicate = build_crypto_price_evidence(
        evidence_id=str(ids["evidence_id"]),
        crypto_price_evidence_id=str(uuid.uuid4()),
        asset="BTC",
        quote_currency="USD",
        price_value="50000",
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert session.scalar(select(func.count()).select_from(CryptoPriceEvidence).where(CryptoPriceEvidence.evidence_id == ids["evidence_id"])) == 1
