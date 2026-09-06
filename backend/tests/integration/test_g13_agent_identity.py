"""G13-A/G13-B persistence and attribution tests without paid traffic."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.identity import get_or_create_m2m_identity
from app.autonomy.service import claim_run, execute_claimed, schedule_due
from app.domain.mandates import AgentIdentity, AutonomyPolicy, AutonomyRun, Mandate, UsageEvent


@pytest.fixture
def session():
    value = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]), autoflush=False)()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


def _policy(name: str, policy_id: str | None = None) -> AutonomyPolicy:
    return AutonomyPolicy(
        policy_id=policy_id or str(uuid.uuid4()),
        name=name,
        enabled=True,
        version="autonomy-policy-v0",
        mandate_template={"title": "G13 test", "instruction": "offline identity test"},
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


def test_m2m_identity_is_stable_and_origin_bound(session):
    agent_id = "g13-m2m-" + str(uuid.uuid4())
    context_id = "m2m-token-sha256:test-context-a"
    first = get_or_create_m2m_identity(session, agent_id, context_id)
    session.flush()
    second = get_or_create_m2m_identity(session, agent_id, context_id)
    assert first.agent_id == second.agent_id == agent_id
    assert first.origin == second.origin == "EXTERNAL_API_AGENT"
    assert first.policy_id is None
    assert first.m2m_context_id == context_id
    assert first.trajectory_version == "g13-agent-identity-v1"


def test_m2m_identity_cannot_cross_authenticated_context(session):
    agent_id = "g13-context-" + str(uuid.uuid4())
    get_or_create_m2m_identity(session, agent_id, "m2m-token-sha256:context-a")
    session.flush()
    with pytest.raises(ValueError, match="M2M_AGENT_CONTEXT_CONFLICT"):
        get_or_create_m2m_identity(session, agent_id, "m2m-token-sha256:context-b")


def test_m2m_identity_race_converges_to_one_canonical_row():
    engine = create_engine(os.environ["DATABASE_URL"], pool_size=4, max_overflow=0)
    factory = sessionmaker(bind=engine, autoflush=False)
    agent_id = "g13-race-" + str(uuid.uuid4())
    context_id = "m2m-token-sha256:race-context"
    barrier = Barrier(2)

    def resolve_identity() -> str:
        local = factory()
        try:
            barrier.wait(timeout=10)
            identity = get_or_create_m2m_identity(local, agent_id, context_id)
            local.commit()
            return identity.agent_id
        finally:
            local.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            resolved = list(workers.map(lambda _item: resolve_identity(), range(2)))
        verifier = factory()
        try:
            rows = verifier.query(AgentIdentity).filter_by(agent_id=agent_id).all()
            assert resolved == [agent_id, agent_id]
            assert len(rows) == 1
            assert rows[0].m2m_context_id == context_id
        finally:
            verifier.query(AgentIdentity).filter_by(agent_id=agent_id).delete(synchronize_session=False)
            verifier.commit()
            verifier.close()
    finally:
        engine.dispose()


def test_autonomy_lineage_requires_persistent_identity_and_propagates_it(session, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GLOBAL_ENABLED", "true")
    policy = _policy("g13-lineage-" + str(uuid.uuid4()))
    identity = AgentIdentity(
        agent_id="g13-internal-" + str(uuid.uuid4()),
        name="G13 internal test",
        origin="INTERNAL_AUTONOMY",
        policy_id=policy.policy_id,
        trajectory_version="g13-agent-identity-v1",
    )
    session.add(policy); session.flush()
    session.add(identity); session.flush()
    run = schedule_due(session, policy, datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc), global_switch=True)
    assert run is not None and run.agent_identity_id == identity.agent_id
    assert claim_run(session, run.run_id) is run
    assert execute_claimed(session, run) == "ACQUISITION_QUEUED"
    mandate = session.get(Mandate, run.mandate_id)
    assert mandate is not None
    assert mandate.agent_identity_id == identity.agent_id
    assert mandate.agent_id == identity.agent_id
    session.flush()
    events = session.query(UsageEvent).filter_by(mandate_id=mandate.mandate_id).all()
    assert events and all(event.metadata_.get("agent_identity_id") == identity.agent_id for event in events)


def test_missing_policy_identity_fails_closed_before_paid_acquisition(session, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GLOBAL_ENABLED", "true")
    policy = _policy("g13-missing-" + str(uuid.uuid4()))
    session.add(policy); session.flush()
    run = schedule_due(session, policy, datetime(2026, 9, 2, 21, 0, tzinfo=timezone.utc), global_switch=True)
    assert run is not None and claim_run(session, run.run_id) is run
    assert execute_claimed(session, run) == "FAILED"
    assert run.failure_code == "AGENT_IDENTITY_MISSING"
    assert run.mandate_id is None


def test_two_policy_identities_do_not_cross_contaminate(session):
    policy_a = _policy("g13-a-" + str(uuid.uuid4()))
    policy_b = _policy("g13-b-" + str(uuid.uuid4()))
    identity_a = AgentIdentity(agent_id="g13-a-" + str(uuid.uuid4()), name="A", origin="INTERNAL_AUTONOMY", policy_id=policy_a.policy_id)
    identity_b = AgentIdentity(agent_id="g13-b-" + str(uuid.uuid4()), name="B", origin="INTERNAL_AUTONOMY", policy_id=policy_b.policy_id)
    session.add_all([policy_a, policy_b]); session.flush()
    session.add_all([identity_a, identity_b]); session.flush()
    run_a = schedule_due(session, policy_a, datetime(2026, 9, 2, 22, 0, tzinfo=timezone.utc), global_switch=True)
    run_b = schedule_due(session, policy_b, datetime(2026, 9, 2, 23, 0, tzinfo=timezone.utc), global_switch=True)
    assert run_a.agent_identity_id == identity_a.agent_id
    assert run_b.agent_identity_id == identity_b.agent_id
