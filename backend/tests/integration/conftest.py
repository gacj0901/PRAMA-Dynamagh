"""Synthetic, rollback-safe fixtures for integration tests on an empty schema."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.domain.mandates import (
    AcquisitionStatus,
    AcquisitionTask,
    Decision,
    ERC8183Job,
    Evidence,
    Mandate,
    StructuralEvaluation,
    Ticket,
)
from app.erc8183.evidence import DIAMOND, RECEIVER, VERSION
from app.pramagraph.evaluation import decide, digest
from app.persistence.database import SessionLocal
from app.tickets.core import build as build_ticket_core, hash_core


SOURCE_MANDATE = "b934092e-33d5-45ff-bf89-c8496803a427"
SOURCE_JOB = "04e5ba3c-d4e2-45d1-a21e-cf10f510916c"
SOURCE_TICKET = "ca4d6936-f0ed-47ee-a2ce-ca509a36c8aa"
SOURCE_ACQUISITION = "g13-fixture-acquisition"
SOURCE_EVALUATION = "g13-fixture-evaluation"
SOURCE_DECISION = "g13-fixture-decision"


@pytest.fixture
def session():
    """Provide the application's real PostgreSQL session to integration tests."""

    value = SessionLocal()
    try:
        yield value
    finally:
        try:
            value.rollback()
        finally:
            value.close()


def _delete_fixture(session) -> None:
    session.execute(text("DELETE FROM evidence WHERE erc8183_job_id = :job"), {"job": SOURCE_JOB})
    session.execute(text("UPDATE erc8183_jobs SET ticket_id = NULL WHERE ticket_id = :ticket"), {"ticket": SOURCE_TICKET})
    session.execute(text("DELETE FROM tickets WHERE ticket_id = :ticket"), {"ticket": SOURCE_TICKET})
    session.execute(text("DELETE FROM decisions WHERE decision_id = :decision"), {"decision": SOURCE_DECISION})
    session.execute(text("DELETE FROM structural_evaluations WHERE evaluation_id = :evaluation"), {"evaluation": SOURCE_EVALUATION})
    session.execute(text("DELETE FROM erc8183_jobs WHERE erc8183_job_id = :job"), {"job": SOURCE_JOB})
    session.execute(text("DELETE FROM acquisition_tasks WHERE acquisition_id = :acquisition"), {"acquisition": SOURCE_ACQUISITION})
    session.execute(text("DELETE FROM mandates WHERE mandate_id = :mandate"), {"mandate": SOURCE_MANDATE})


@pytest.fixture(scope="session", autouse=True)
def synthetic_g9_fixture():
    """Make legacy G0-G12 integration checks self-contained and non-production."""
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = sessionmaker(bind=engine, autoflush=False)
    session = factory()
    try:
        _delete_fixture(session)
        session.commit()

        mandate = Mandate(
            mandate_id=SOURCE_MANDATE,
            actor_id="g13-integration-fixture",
            text="Synthetic persisted G9 regression fixture",
            mandate_type="GENERAL",
            constraints={},
            max_budget_usdc=Decimal("0"),
            status="TICKETED",
            origin="MANUAL",
        )
        acquisition = AcquisitionTask(
            acquisition_id=SOURCE_ACQUISITION,
            mandate_id=SOURCE_MANDATE,
            query="Synthetic persisted G9 regression fixture",
            requested_intent="STORM_ALERT",
            required=True,
            status=AcquisitionStatus.SUCCEEDED.value,
            ordinal=0,
            attempt_count=1,
        )
        normalized_payload = {"fixture": "g13", "status": "terminal"}
        content_hash = digest(normalized_payload)
        evidence = Evidence(
            evidence_id="g13-fixture-evidence",
            mandate_id=SOURCE_MANDATE,
            acquisition_id=SOURCE_ACQUISITION,
            telegraph_call_id=None,
            erc8183_job_id=SOURCE_JOB,
            evidence_type="TELEGRAPH_ERC8183_RESULT",
            source_kind="TELEGRAPH_ERC8183",
            source_intent="STORM_ALERT",
            source_miner_id=None,
            source_signal_hash=None,
            normalized_payload=normalized_payload,
            content_hash=content_hash,
            normalizer_version=VERSION,
            provenance_status="VERIFIED",
            admissibility="ADMITTED",
            limitation_codes=[],
        )
        evaluation = StructuralEvaluation(
            evaluation_id=SOURCE_EVALUATION,
            mandate_id=SOURCE_MANDATE,
            evaluator="PRAMAGRAPH",
            evaluator_version="pramagraph-structural-v0",
            evidence_set_hash=digest([content_hash]),
            admitted_evidence_ids=[evidence.evidence_id],
            limited_evidence_ids=[],
            rejected_evidence_ids=[],
            limitation_codes=[],
            contradiction_codes=[],
            structural_state="STRUCTURALLY_ADMISSIBLE",
            evaluation_payload={"source": "synthetic-test-fixture"},
        )
        decision_state, reason_codes = decide(evaluation.structural_state)
        decision = Decision(
            decision_id=SOURCE_DECISION,
            mandate_id=SOURCE_MANDATE,
            evaluation_id=SOURCE_EVALUATION,
            state=decision_state,
            policy_version="prama-gate-v0",
            evidence_set_hash=evaluation.evidence_set_hash,
            reason_codes=reason_codes,
            decision_payload={},
        )
        ticket_core = build_ticket_core(mandate, decision, evaluation, [evidence], [], [acquisition])
        ticket = Ticket(
            ticket_id=SOURCE_TICKET,
            mandate_id=SOURCE_MANDATE,
            decision_id=SOURCE_DECISION,
            schema_version="prama.ticket.v0",
            canonical_payload=ticket_core,
            ticket_hash=hash_core(ticket_core),
            hash_algorithm="keccak256",
            anchor_status="LOCAL_ONLY",
        )
        job = ERC8183Job(
            erc8183_job_id=SOURCE_JOB,
            mandate_id=SOURCE_MANDATE,
            ticket_id=None,
            chain_id=84532,
            diamond_address=DIAMOND,
            telegraph_job_id="27",
            intent_name="STORM_ALERT",
            intent_id="0x" + "11" * 32,
            callback_address=RECEIVER,
            callback_verified=True,
            params_payload={},
            state="TERMINAL",
            chain_state="COMPLETED",
            budget_usdc=Decimal("0"),
            miner_payment_usdc=Decimal("0"),
            protocol_fee_usdc=Decimal("0"),
        )
        session.add(mandate)
        session.flush()
        session.add(acquisition)
        session.flush()
        session.add(job)
        session.flush()
        session.add(evidence)
        session.flush()
        session.add_all([evaluation, decision, ticket])
        session.flush()
        job.ticket_id = SOURCE_TICKET
        session.commit()
        yield
    finally:
        session.rollback()
        _delete_fixture(session)
        session.commit()
        session.close()
        engine.dispose()
