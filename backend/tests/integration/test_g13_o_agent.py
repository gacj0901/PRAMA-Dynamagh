"""PostgreSQL-backed G13-C O_AGENT observations without external traffic."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.observation import build_o_agent_stream
from app.domain.mandates import (
    AcquisitionStatus,
    AcquisitionTask,
    AgentIdentity,
    AutonomyPolicy,
    AutonomyRun,
    Decision,
    Evidence,
    Mandate,
    PublicManualSpendReservation,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.pramagraph.evaluation import digest


@pytest.fixture
def session():
    value = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]), autoflush=False)()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


def _identity(session, *, origin: str, suffix: str, when: datetime) -> tuple[AgentIdentity, AutonomyPolicy | None]:
    policy = None
    policy_id = None
    if origin == "INTERNAL_AUTONOMY":
        policy = AutonomyPolicy(
            policy_id=str(uuid.uuid4()),
            name="g13-o-agent-" + suffix,
            enabled=True,
            version="autonomy-policy-v0",
            mandate_template={"instruction": "offline observation fixture"},
            acquisition_mode="TELEGRAPH_HTTP",
            allow_telegraph_http=True,
            allow_erc8183=False,
            allow_anchor=False,
            strict_verification=True,
            read_only_replay=False,
            cadence_seconds=900,
            dedupe_window_seconds=900,
            max_usdc_per_run=Decimal("0.010000"),
            max_usdc_per_day=Decimal("0.030000"),
            max_runs_per_day=3,
            max_concurrent_runs=1,
            state="ACTIVE",
        )
        session.add(policy)
        session.flush()
        policy_id = policy.policy_id
    identity = AgentIdentity(
        agent_id="g13-o-agent-" + suffix,
        name="O_AGENT " + suffix,
        origin=origin,
        policy_id=policy_id,
        m2m_context_id="m2m-token-sha256:" + suffix if origin == "EXTERNAL_API_AGENT" else None,
        trajectory_version="g13-agent-identity-v1",
        created_at=when,
    )
    session.add(identity)
    session.flush()
    return identity, policy


def _m2m_mandate(session, identity: AgentIdentity, *, ordinal: int, when: datetime, decision_state: str = "PERMIT") -> Mandate:
    mandate = Mandate(
        mandate_id=str(uuid.uuid4()),
        actor_id=identity.agent_id,
        text="offline M2M observation fixture",
        mandate_type="CRYPTO_PRICE",
        constraints={},
        max_budget_usdc=Decimal("0.010000"),
        status="TICKETED",
        origin="M2M",
        agent_id=identity.agent_id,
        agent_identity_id=identity.agent_id,
        m2m_context_id=identity.m2m_context_id,
        client_id="client-" + identity.agent_id,
        created_at=when,
    )
    session.add(mandate)
    session.flush()
    task = AcquisitionTask(
        acquisition_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        query=mandate.text,
        requested_intent="CRYPTO_PRICE",
        required=True,
        status=AcquisitionStatus.SUCCEEDED.value,
        ordinal=ordinal,
        attempt_count=ordinal + 1,
        created_at=when + timedelta(seconds=ordinal),
    )
    session.add(task)
    session.flush()
    call = TelegraphCall(
        telegraph_call_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        acquisition_id=task.acquisition_id,
        causal_request_id=str(uuid.uuid4()),
        intent="CRYPTO_PRICE",
        cost_usd=Decimal("0.001000"),
        duration_ms=None if ordinal == 0 else 125,
        raw_response={},
        warnings=[],
        status="SUCCEEDED",
        created_at=when + timedelta(seconds=ordinal + 1),
    )
    evidence_payload = {"fixture": "o-agent", "ordinal": ordinal}
    evidence = Evidence(
        evidence_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        acquisition_id=task.acquisition_id,
        normalized_payload=evidence_payload,
        content_hash=digest(evidence_payload),
        normalizer_version="o-agent-test-v0",
        provenance_status="VERIFIED",
        admissibility="ADMITTED",
        limitation_codes=[],
        evidence_type="TELEGRAPH_HTTP_RESULT",
        source_kind="TELEGRAPH_HTTP",
        source_intent="CRYPTO_PRICE",
        created_at=when + timedelta(seconds=4),
    )
    evaluation = StructuralEvaluation(
        evaluation_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        evaluator="PRAMAGRAPH",
        evaluator_version="test-v0",
        evidence_set_hash=digest([evidence.content_hash]),
        admitted_evidence_ids=[evidence.evidence_id],
        limited_evidence_ids=[],
        rejected_evidence_ids=[],
        limitation_codes=[],
        contradiction_codes=[],
        structural_state="STRUCTURALLY_ADMISSIBLE",
        evaluation_payload={},
        created_at=when + timedelta(seconds=5),
    )
    decision = Decision(
        decision_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        evaluation_id=evaluation.evaluation_id,
        state=decision_state,
        policy_version="prama-gate-v0",
        evidence_set_hash=evaluation.evidence_set_hash,
        reason_codes=["ALL_REQUIRED_EVIDENCE_ADMITTED"],
        decision_payload={},
        created_at=when + timedelta(seconds=6),
    )
    ticket_payload = {"fixture": "o-agent", "mandate_id": mandate.mandate_id}
    ticket = Ticket(
        ticket_id=str(uuid.uuid4()),
        mandate_id=mandate.mandate_id,
        decision_id=decision.decision_id,
        schema_version="prama.ticket.v0",
        canonical_payload=ticket_payload,
        ticket_hash=digest(ticket_payload),
        hash_algorithm="keccak256",
        anchor_status="LOCAL_ONLY",
        created_at=when + timedelta(seconds=7),
    )
    reservation = PublicManualSpendReservation(
        mandate_id=mandate.mandate_id,
        spend_date=when.date(),
        reserved_usdc=Decimal("0.001000"),
        actual_spend_usdc=Decimal("0.001000"),
        status="SETTLED",
        origin="M2M",
        created_at=when + timedelta(seconds=2),
    )
    session.add_all([call, evidence, evaluation, decision, ticket, reservation])
    session.add(
        UsageEvent(
            mandate_id=mandate.mandate_id,
            event_type="DECISION_CREATED",
            metadata_={"agent_identity_id": identity.agent_id, "origin": "M2M"},
            created_at=when + timedelta(seconds=3),
        )
    )
    session.flush()
    return mandate


def test_o_agent_m2m_ordering_lineage_repeated_permit_and_missing_telemetry(session):
    base = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    identity, _ = _identity(session, origin="EXTERNAL_API_AGENT", suffix=str(uuid.uuid4()), when=base)
    first = _m2m_mandate(session, identity, ordinal=0, when=base + timedelta(minutes=1))
    second = _m2m_mandate(session, identity, ordinal=1, when=base + timedelta(minutes=2))
    stream = build_o_agent_stream(session, identity.agent_id, start=base, end=base + timedelta(minutes=4))
    assert stream
    assert [item.sequence for item in stream] == list(range(1, len(stream) + 1))
    assert all(item.origin_surface == "M2M" for item in stream)
    assert all(item.agent_identity_id == identity.agent_id for item in stream)
    assert all(item.source_lineage.agent_identity_id == identity.agent_id for item in stream)
    assert {item.source_id for item in stream if item.source_kind == "MANDATE"} == {first.mandate_id, second.mandate_id}
    assert sum(item.facts.local_decision_state == "PERMIT" for item in stream) >= 2
    first_call = next(item for item in stream if item.source_kind == "TELEGRAPH_CALL" and item.source_lineage.mandate_ids == (first.mandate_id,))
    assert first_call.facts.latency_ms is None
    assert "TELEGRAPH_LATENCY_NOT_AVAILABLE" in first_call.missing_data
    assert all(stream[index].observed_at <= stream[index + 1].observed_at for index in range(len(stream) - 1))


def test_o_agent_autonomous_failure_recovery_and_replay_equivalence(session):
    base = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)
    identity, policy = _identity(session, origin="INTERNAL_AUTONOMY", suffix=str(uuid.uuid4()), when=base)
    mandate = Mandate(
        mandate_id=str(uuid.uuid4()),
        actor_id=identity.agent_id,
        text="offline autonomous observation fixture",
        mandate_type="CRYPTO_PRICE",
        constraints={},
        max_budget_usdc=Decimal("0.010000"),
        status="FAILED",
        origin="AUTONOMOUS",
        agent_id=identity.agent_id,
        agent_identity_id=identity.agent_id,
        autonomy_policy_id=policy.policy_id,
        created_at=base + timedelta(minutes=1),
    )
    session.add(mandate)
    session.flush()
    failed = AutonomyRun(
        run_id=str(uuid.uuid4()),
        policy_id=policy.policy_id,
        agent_identity_id=identity.agent_id,
        mandate_id=mandate.mandate_id,
        scheduled_for=base + timedelta(minutes=1),
        idempotency_key="o-agent-failed-" + str(uuid.uuid4()),
        state="FAILED",
        failure_code="TELEGRAPH_TIMEOUT",
        planned_cost_usdc=Decimal("0.010000"),
        actual_cost_usdc=Decimal("0"),
        started_at=base + timedelta(minutes=1),
        finished_at=base + timedelta(minutes=1, seconds=2),
    )
    recovered = AutonomyRun(
        run_id=str(uuid.uuid4()),
        policy_id=policy.policy_id,
        agent_identity_id=identity.agent_id,
        mandate_id=None,
        scheduled_for=base + timedelta(minutes=16),
        idempotency_key="o-agent-recovered-" + str(uuid.uuid4()),
        state="COMPLETED",
        planned_cost_usdc=Decimal("0.010000"),
        actual_cost_usdc=Decimal("0.001000"),
        started_at=base + timedelta(minutes=16),
        finished_at=base + timedelta(minutes=16, seconds=2),
    )
    session.add_all([failed, recovered])
    session.add_all([
        UsageEvent(mandate_id=mandate.mandate_id, event_type="AUTONOMY_RUN_FAILED", metadata_={"agent_identity_id": identity.agent_id, "autonomy_run_id": failed.run_id}, created_at=failed.finished_at),
        UsageEvent(mandate_id=None, event_type="AUTONOMY_RUN_COMPLETED", metadata_={"agent_identity_id": identity.agent_id, "autonomy_run_id": recovered.run_id}, created_at=recovered.finished_at),
    ])
    session.flush()
    first = build_o_agent_stream(session, identity.agent_id)
    second = build_o_agent_stream(session, identity.agent_id)
    assert [item.canonical_bytes() for item in first] == [item.canonical_bytes() for item in second]
    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    failed_observation = next(item for item in first if item.source_id == failed.run_id)
    recovered_observation = next(item for item in first if item.source_id == recovered.run_id)
    assert failed_observation.origin_surface == "AUTONOMOUS"
    assert failed_observation.facts.failure_code == "TELEGRAPH_TIMEOUT"
    assert recovered_observation.facts.recovered is True
    assert recovered_observation.facts.trajectory_viability is None
    assert recovered_observation.facts.local_decision_scope is None
    bounded = build_o_agent_stream(session, identity.agent_id, run_id=recovered.run_id)
    assert {item.source_id for item in bounded} <= {identity.agent_id, recovered.run_id}


def test_o_agent_cross_agent_scope_isolated_and_run_handle_cannot_cross(session):
    base = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
    first_identity, _ = _identity(session, origin="EXTERNAL_API_AGENT", suffix=str(uuid.uuid4()), when=base)
    second_identity, _ = _identity(session, origin="EXTERNAL_API_AGENT", suffix=str(uuid.uuid4()), when=base)
    first = _m2m_mandate(session, first_identity, ordinal=0, when=base + timedelta(minutes=1))
    second = _m2m_mandate(session, second_identity, ordinal=0, when=base + timedelta(minutes=1))
    other_policy = AutonomyPolicy(
        policy_id=str(uuid.uuid4()), name="g13-o-agent-scope-" + str(uuid.uuid4()), enabled=False,
        version="autonomy-policy-v0", mandate_template={}, acquisition_mode="TELEGRAPH_HTTP",
        allow_telegraph_http=False, allow_erc8183=False, allow_anchor=False, strict_verification=True,
        read_only_replay=False, cadence_seconds=900, dedupe_window_seconds=900,
        max_usdc_per_run=Decimal("0"), max_usdc_per_day=Decimal("0"), max_runs_per_day=0,
        max_concurrent_runs=1, state="DRAFT",
    )
    session.add(other_policy)
    session.flush()
    other_run = AutonomyRun(
        run_id=str(uuid.uuid4()), policy_id=other_policy.policy_id,
        agent_identity_id=second_identity.agent_id, scheduled_for=base + timedelta(minutes=3),
        idempotency_key="o-agent-scope-" + str(uuid.uuid4()), state="SCHEDULED",
        planned_cost_usdc=Decimal("0"), actual_cost_usdc=Decimal("0"),
    )
    session.add(other_run)
    session.flush()
    first_stream = build_o_agent_stream(session, first_identity.agent_id)
    second_stream = build_o_agent_stream(session, second_identity.agent_id)
    first_ids = {item.source_id for item in first_stream}
    second_ids = {item.source_id for item in second_stream}
    assert first.mandate_id in first_ids and second.mandate_id not in first_ids
    assert second.mandate_id in second_ids and first.mandate_id not in second_ids
    with pytest.raises(ValueError, match="AGENT_RUN_SCOPE_MISMATCH"):
        build_o_agent_stream(session, first_identity.agent_id, run_id=other_run.run_id)
