"""G10-A persistence and fail-closed scheduler tests.

These tests only create rollback-scoped PostgreSQL rows.  The replay fixture
uses the already persisted G9 artifact and never calls the Gateway or chain.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.autonomy.service import (
    PAID_MIN_CADENCE_SECONDS,
    claim_run,
    execute_claimed,
    execution_slot,
    idempotency_key,
    recover_runs,
    schedule_due,
    status,
    validate_policy,
)
from app.domain.mandates import AcquisitionTask, AgentAuthorityProfile, AgentIdentity, AutonomyPolicy, AutonomyRun, Mandate, PublicManualSpendReservation, UsageEvent
from app.main import app

LIVE_G9_JOB = "04e5ba3c-d4e2-45d1-a21e-cf10f510916c"


@pytest.fixture
def session():
    value = sessionmaker(bind=create_engine(os.environ["DATABASE_URL"]), autoflush=False)()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


def policy(**overrides) -> AutonomyPolicy:
    values = {
        "name": "g10-test-" + str(uuid.uuid4()), "enabled": True,
        "version": "autonomy-policy-v0", "mandate_template": {},
        "acquisition_mode": "TELEGRAPH_HTTP", "allow_telegraph_http": True,
        "allow_erc8183": False, "allow_anchor": False,
        "strict_verification": True, "read_only_replay": False,
        "cadence_seconds": PAID_MIN_CADENCE_SECONDS,
        "dedupe_window_seconds": PAID_MIN_CADENCE_SECONDS,
        "max_usdc_per_run": Decimal("0.050000"),
        "max_usdc_per_day": Decimal("0.200000"),
        "max_runs_per_day": 4, "max_concurrent_runs": 1, "state": "ACTIVE",
    }
    values.update(overrides)
    return AutonomyPolicy(**values)


def authority_profile(agent_id: str, **overrides) -> AgentAuthorityProfile:
    from app.authority.profiles import compute_authority_hash
    values = dict(
        version=1, created_by="pytest",
        principal_id="g13-autonomy-test-principal", agent_identity_id=agent_id,
        status="ACTIVE", valid_from=datetime.now(timezone.utc) - timedelta(seconds=1),
        allowed_intents=[], allowed_action_kinds=[], economic_budget=Decimal("0.050000"),
        per_action_budget=Decimal("0.050000"), rolling_budget=None, concurrency_limit=1,
        cadence_policy=None, external_execution_allowed=True, telegraph_allowed=True,
        anchoring_allowed=False, erc8183_allowed=False, human_review_thresholds={},
        policy_version="agent-authority-v0",
    )
    values.update(overrides)
    profile = AgentAuthorityProfile(**values)
    profile.authority_hash = compute_authority_hash(profile)
    return profile


def test_validation_defaults_and_public_template_boundary():
    valid = {
        "acquisition_mode": "TELEGRAPH_HTTP", "allow_telegraph_http": True,
        "allow_erc8183": False, "mandate_template": {},
        "cadence_seconds": 900, "dedupe_window_seconds": 900,
        "max_usdc_per_run": "0.05", "max_usdc_per_day": "0.20",
        "max_runs_per_day": 4, "max_concurrent_runs": 1,
    }
    validate_policy(valid)
    candidate = dict(valid); candidate["cadence_seconds"] = 60
    validate_policy(candidate)
    for changed, code in (
        ({"dedupe_window_seconds": 1}, "AUTONOMY_DEDUPE_WINDOW_INVALID"),
        ({"mandate_template": {"private_key": "blocked"}}, "AUTONOMY_TEMPLATE_FORBIDDEN_FIELD"),
    ):
        candidate = dict(valid); candidate.update(changed)
        with pytest.raises(ValueError, match=code):
            validate_policy(candidate)
    draft = policy(enabled=False, state="DRAFT", allow_anchor=False, max_concurrent_runs=1)
    assert draft.enabled is False and draft.allow_anchor is False and draft.max_concurrent_runs == 1


def test_disabled_global_slot_idempotency_and_single_claim(session):
    value = policy(); session.add(value); session.flush()
    instant = datetime(2026, 9, 2, 12, 7, tzinfo=timezone.utc)
    value.enabled = False
    assert schedule_due(session, value, instant, global_switch=True) is None
    value.enabled = True
    assert schedule_due(session, value, instant, global_switch=False) is None
    run = schedule_due(session, value, instant, global_switch=True)
    assert run is not None and run.state == "SCHEDULED"
    assert run.idempotency_key == idempotency_key(value, execution_slot(value, instant))
    assert schedule_due(session, value, instant, global_switch=True).run_id == run.run_id
    session.flush()
    assert len([event for event in session.query(UsageEvent).filter_by(event_type="AUTONOMY_RUN_SCHEDULED") if event.metadata_.get("autonomy_run_id") == run.run_id]) == 1
    assert session.query(AutonomyRun).filter_by(policy_id=value.policy_id).count() == 1
    assert claim_run(session, run.run_id).state == "CLAIMED"
    session.flush()
    assert claim_run(session, run.run_id) is None
    value.enabled = False; value.state = "PAUSED"; value.next_run_at = None
    assert schedule_due(session, value, instant + timedelta(seconds=PAID_MIN_CADENCE_SECONDS), global_switch=True) is None


def test_two_worker_sessions_have_one_durable_claim_winner():
    engine = create_engine(os.environ["DATABASE_URL"])
    factory = sessionmaker(bind=engine, autoflush=False)
    owner = factory(); rival = factory(); cleanup = factory()
    policy_id = run_id = None
    try:
        value = policy(); owner.add(value); owner.flush()
        run = schedule_due(owner, value, datetime(2026, 9, 2, 13, tzinfo=timezone.utc), global_switch=True)
        policy_id, run_id = value.policy_id, run.run_id
        owner.commit()
        assert claim_run(owner, run_id).run_id == run_id
        owner.flush()  # holds the PostgreSQL FOR UPDATE lease
        assert claim_run(rival, run_id) is None
        owner.commit()
        assert claim_run(rival, run_id) is None
    finally:
        rival.rollback(); owner.rollback()
        if policy_id:
            cleanup.execute(text("DELETE FROM autonomy_policies WHERE policy_id = :policy_id"), {"policy_id": policy_id})
        cleanup.commit()
        cleanup.close(); rival.close(); owner.close()


def test_caps_and_restart_recovery_are_persistent(session):
    instant = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)
    value = policy(max_runs_per_day=1); session.add(value); session.flush()
    session.add(AutonomyRun(policy_id=value.policy_id, scheduled_for=instant - timedelta(hours=1), idempotency_key="cap-" + str(uuid.uuid4()), state="COMPLETED", planned_cost_usdc=Decimal("0.05"), actual_cost_usdc=Decimal("0.05")))
    session.flush()
    assert schedule_due(session, value, instant, global_switch=True).skip_reason == "DAILY_RUN_CAP"

    budget = policy(max_usdc_per_day=Decimal("0.050000")); session.add(budget); session.flush()
    session.add(AutonomyRun(policy_id=budget.policy_id, scheduled_for=instant - timedelta(hours=1), idempotency_key="budget-" + str(uuid.uuid4()), state="COMPLETED", planned_cost_usdc=Decimal("0.05"), actual_cost_usdc=Decimal("0.05")))
    session.flush()
    assert schedule_due(session, budget, instant, global_switch=True).skip_reason == "DAILY_BUDGET_CAP"

    concurrent = policy(); session.add(concurrent); session.flush()
    session.add(AutonomyRun(policy_id=concurrent.policy_id, scheduled_for=instant - timedelta(hours=1), idempotency_key="active-" + str(uuid.uuid4()), state="RUNNING", planned_cost_usdc=Decimal("0.05"), actual_cost_usdc=Decimal("0")))
    session.flush()
    assert schedule_due(session, concurrent, instant, global_switch=True).skip_reason == "CONCURRENCY_CAP"

    restart = policy(); session.add(restart); session.flush()
    claimed = AutonomyRun(policy_id=restart.policy_id, scheduled_for=instant, idempotency_key="restart-" + str(uuid.uuid4()), state="RUNNING", planned_cost_usdc=Decimal("0"), actual_cost_usdc=Decimal("0"))
    waiting = AutonomyRun(policy_id=restart.policy_id, scheduled_for=instant, idempotency_key="waiting-" + str(uuid.uuid4()), state="WAITING_EXTERNAL", erc8183_job_id=LIVE_G9_JOB, planned_cost_usdc=Decimal("0"), actual_cost_usdc=Decimal("0"))
    session.add_all([claimed, waiting]); session.flush()
    assert claimed.run_id in recover_runs(session)
    assert claimed.state == "SCHEDULED" and waiting.state == "WAITING_EXTERNAL"


def test_explicit_unlimited_profile_bypasses_usage_caps_but_keeps_concurrency(session, monkeypatch):
    value = policy(
        mandate_template={"title": "Unlimited authority", "instruction": "Run authorized acquisition"},
        max_runs_per_day=1,
        max_usdc_per_run=Decimal("0.010000"),
        max_usdc_per_day=Decimal("0.010000"),
    )
    session.add(value); session.flush()
    identity = AgentIdentity(
        agent_id="unlimited-" + str(uuid.uuid4()), name="Unlimited authority test",
        origin="INTERNAL_AUTONOMY", policy_id=value.policy_id,
    )
    session.add(identity); session.flush()
    session.add(authority_profile(
        identity.agent_id,
        principal_id=None,
        economic_budget=None,
        per_action_budget=None,
        unlimited_budget=True,
        unlimited_execution_rate=True,
    )); session.flush()
    prior = AutonomyRun(
        policy_id=value.policy_id,
        agent_identity_id=identity.agent_id,
        scheduled_for=datetime(2026, 9, 2, 19, tzinfo=timezone.utc),
        idempotency_key="unlimited-prior-" + str(uuid.uuid4()),
        state="COMPLETED",
        planned_cost_usdc=Decimal("25.000000"),
        actual_cost_usdc=Decimal("25.000000"),
    )
    session.add(prior); session.flush()
    monkeypatch.setenv("FULL_AUTONOMY_ENABLED", "true")
    instant = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)
    run = schedule_due(session, value, instant, global_switch=True)
    assert run.state == "SCHEDULED" and run.skip_reason is None
    assert run.planned_cost_usdc == 0
    assert value.next_run_at == instant + timedelta(seconds=1)
    assert claim_run(session, run.run_id) is run
    import app.autonomy.service as autonomy
    monkeypatch.setattr(autonomy, "global_enabled", lambda: True)
    assert execute_claimed(session, run) == "ACQUISITION_QUEUED"
    reservation = session.get(PublicManualSpendReservation, run.mandate_id)
    assert reservation.origin == "AUTONOMOUS"
    assert reservation.reserved_usdc == 0


def test_replay_only_scheduler_is_db_only_and_manual_records_coexist(session, monkeypatch):
    source_mandate = session.get(Mandate, "b934092e-33d5-45ff-bf89-c8496803a427")
    assert source_mandate is not None and source_mandate.origin == "MANUAL"
    value = policy(
        acquisition_mode="REPLAY_ONLY", allow_telegraph_http=False,
        read_only_replay=True, mandate_template={"erc8183_job_id": LIVE_G9_JOB},
        max_usdc_per_run=Decimal("0"), max_usdc_per_day=Decimal("0"),
    )
    session.add(value); session.flush()
    instant = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
    run = schedule_due(session, value, instant, global_switch=True)
    assert claim_run(session, run.run_id) is run
    import app.erc8183.evidence as evidence
    monkeypatch.setattr(evidence, "_gateway", lambda _path: pytest.fail("network access is forbidden"))
    assert execute_claimed(session, run) == "COMPLETED"
    assert run.actual_cost_usdc == Decimal("0.000000") and run.mandate_id == source_mandate.mandate_id
    autonomous = Mandate(
        actor_id="autonomy-controller", text="rollback-only autonomous fixture",
        mandate_type="GENERAL", constraints={}, max_budget_usdc=Decimal("0"),
        origin="AUTONOMOUS", autonomy_policy_id=value.policy_id, autonomy_run_id=run.run_id,
    )
    session.add(autonomous); session.flush()
    assert autonomous.origin == "AUTONOMOUS" and autonomous.autonomy_policy_id == value.policy_id and autonomous.autonomy_run_id == run.run_id
    metrics = status(session, instant)
    assert metrics["completed"] >= 1 and run.actual_cost_usdc == Decimal("0.000000")


def test_replay_failure_is_terminal_and_emits_one_failed_event(session, monkeypatch):
    value = policy(
        acquisition_mode="REPLAY_ONLY", allow_telegraph_http=False,
        read_only_replay=True, mandate_template={"erc8183_job_id": LIVE_G9_JOB},
        max_usdc_per_run=Decimal("0"), max_usdc_per_day=Decimal("0"),
    )
    session.add(value); session.flush()
    run = schedule_due(session, value, datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc), global_switch=True)
    claim_run(session, run.run_id)
    import app.autonomy.service as autonomy
    monkeypatch.setattr(autonomy, "replay_persisted", lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")))
    assert execute_claimed(session, run) == "FAILED" and run.failure_code == "REPLAY_FAILED"
    session.flush()
    assert len([event for event in session.query(UsageEvent).filter_by(event_type="AUTONOMY_RUN_FAILED") if event.metadata_.get("autonomy_run_id") == run.run_id]) == 1


def test_http_scheduler_originates_an_autonomous_mandate_without_network(session, monkeypatch):
    value = policy(mandate_template={"title": "Autonomous Bitcoin price verification", "instruction": "What is the current price of Bitcoin in USD?"})
    session.add(value); session.flush()
    identity = AgentIdentity(
        agent_id="g13-autonomy-test-" + str(uuid.uuid4()),
        name="G13 autonomy test",
        origin="INTERNAL_AUTONOMY",
        policy_id=value.policy_id,
        trajectory_version="g13-agent-identity-v1",
    )
    session.add(identity); session.flush()
    session.add(authority_profile(identity.agent_id)); session.flush()
    monkeypatch.setenv("FULL_AUTONOMY_ENABLED", "true")
    run = schedule_due(session, value, datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc), global_switch=True)
    assert claim_run(session, run.run_id) is run
    import app.autonomy.service as autonomy
    monkeypatch.setattr(autonomy, "global_enabled", lambda: True)
    assert execute_claimed(session, run) == "ACQUISITION_QUEUED"
    session.flush()
    mandate = session.get(Mandate, run.mandate_id)
    acquisition = session.query(AcquisitionTask).filter_by(mandate_id=run.mandate_id).one()
    assert run.state == "RUNNING" and run.agent_identity_id == identity.agent_id and mandate.origin == "AUTONOMOUS"
    assert mandate.autonomy_policy_id == value.policy_id and mandate.autonomy_run_id == run.run_id
    assert mandate.agent_identity_id == identity.agent_id and mandate.agent_id == identity.agent_id
    assert acquisition.status == "QUEUED" and acquisition.query == mandate.text


def test_status_endpoint_is_read_only_and_policy_api_rejects_secret_template():
    client = TestClient(app)
    response = client.get("/v1/autonomy/status")
    assert response.status_code == 200 and "global_enabled" in response.json()
    blocked = client.post("/v1/autonomy/policies", json={
        "name": "blocked-" + str(uuid.uuid4()), "acquisition_mode": "TELEGRAPH_HTTP",
        "allow_telegraph_http": True, "mandate_template": {"callback_contract": "no"},
    })
    assert blocked.status_code == 422


def test_policy_management_endpoints_keep_safe_defaults_and_enable_disable():
    client = TestClient(app)
    name = "api-policy-" + str(uuid.uuid4())
    created = client.post("/v1/autonomy/policies", json={
        "name": name, "acquisition_mode": "TELEGRAPH_HTTP", "allow_telegraph_http": True,
        "mandate_template": {"purpose": "rollback-only API test"},
    })
    assert created.status_code == 201
    policy_id = created.json()["policy_id"]
    try:
        payload = created.json()
        assert payload["enabled"] is False and payload["allow_anchor"] is False and payload["max_concurrent_runs"] == 1
        assert client.get(f"/v1/autonomy/policies/{policy_id}").status_code == 200
        assert client.patch(f"/v1/autonomy/policies/{policy_id}", json={"max_runs_per_day": 3}).json()["max_runs_per_day"] == 3
        assert client.post(f"/v1/autonomy/policies/{policy_id}/enable").json()["state"] == "ACTIVE"
        disabled = client.post(f"/v1/autonomy/policies/{policy_id}/disable").json()
        assert disabled["enabled"] is False and disabled["state"] == "PAUSED"
    finally:
        with create_engine(os.environ["DATABASE_URL"]).begin() as connection:
            connection.execute(text("DELETE FROM autonomy_policies WHERE policy_id = :policy_id"), {"policy_id": policy_id})
