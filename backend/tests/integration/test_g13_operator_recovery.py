from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from app.agents.observation import build_o_agent_stream
from app.authority.recovery import (
    G13_OPERATOR_RECOVERY_POLICY_VERSION,
    G13_RECOVERY_EVENT_TYPE,
    G13_REVIEW_RECOVERY_POLICY_VERSION,
    latest_operator_recovery,
    record_operator_recovery,
    record_review_recovery,
    validate_recovery_payload,
)
from app.domain.mandates import AgentIdentity, PolicyEvaluation, UsageEvent


def test_recovery_event_is_idempotent_hashed_and_visible_to_o_agent(session):
    agent_id = "recovery-agent-" + str(uuid.uuid4())
    identity = AgentIdentity(
        agent_id=agent_id,
        name="Recovery fixture",
        origin="INTERNAL_AUTONOMY",
        status="ACTIVE",
        autonomy_state="REVIEW_REQUIRED",
    )
    first_source = UsageEvent(
        event_id=str(uuid.uuid4()),
        mandate_id=None,
        event_type="AUTONOMY_RUN_FAILED",
        metadata_={"agent_identity_id": agent_id},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )
    second_source = UsageEvent(
        event_id=str(uuid.uuid4()),
        mandate_id=None,
        event_type="ACQUISITION_FAILED",
        metadata_={"agent_identity_id": agent_id},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    session.add_all([identity, first_source, second_source])
    session.flush()
    instant = datetime.now(timezone.utc)
    arguments = dict(
        agent_identity_id=agent_id,
        previous_failure_rules=["G13_REPEATED_LOCAL_BLOCK", "G13_REPEATED_EXECUTION_FAILURE"],
        previous_endpoint_reference="https://devnode.telegraphprotocol.com",
        new_endpoint="http://13.237.89.59:7044",
        gateway_deployment_id="72afe908-bd36-42a2-8df0-0cff751054f3",
        authority_mode="BINDING",
        previous_policy_version="g13-d-structural-autonomy-v0.2",
        source_event_ids=[first_source.event_id, second_source.event_id],
        created_at=instant,
        canary_budget_usdc=Decimal("0.010000"),
    )
    event = record_operator_recovery(session, **arguments)
    same = record_operator_recovery(session, **arguments)
    assert same.event_id == event.event_id
    assert event.event_type == G13_RECOVERY_EVENT_TYPE
    assert validate_recovery_payload(event.metadata_) is True
    assert latest_operator_recovery(session, agent_id).event_id == event.event_id
    observations = build_o_agent_stream(session, agent_id)
    projected = next(item for item in observations if item.source_id == event.event_id)
    assert projected.facts.action_status == G13_RECOVERY_EVENT_TYPE
    assert projected.facts.recovery_event_types == (G13_RECOVERY_EVENT_TYPE,)


def test_review_recovery_requires_a_review_and_reconciled_no_payment_source(session):
    agent_id = "review-recovery-agent-" + str(uuid.uuid4())
    evaluation_id = str(uuid.uuid4())
    source_event_id = str(uuid.uuid4())
    identity = AgentIdentity(
        agent_id=agent_id,
        name="Review recovery fixture",
        origin="INTERNAL_AUTONOMY",
        status="ACTIVE",
        autonomy_state="REVIEW_REQUIRED",
    )
    evaluation = PolicyEvaluation(
        policy_evaluation_id=evaluation_id,
        policy_id="G13_STRUCTURAL_AUTONOMY_POLICY_V0_3",
        policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        policy_type="STRUCTURAL_AUTONOMY",
        policy_subject_type="AGENT_IDENTITY",
        policy_subject_id=agent_id,
        observation_refs=[],
        observation_contract_versions={"o_agent": "o-agent-v0"},
        input_core={"fixture": True},
        input_hash="0x" + "1" * 64,
        triggered_rule_ids=["G13_REPEATED_EXECUTION_FAILURE"],
        result="REVIEW",
        result_core={"autonomy_state": "REVIEW"},
        result_hash="0x" + "2" * 64,
        replay_identity="0x" + uuid.uuid4().hex * 2,
    )
    reconciliation = UsageEvent(
        event_id=source_event_id,
        mandate_id=None,
        event_type="ACQUISITION_PAYMENT_RECONCILED",
        metadata_={"agent_identity_id": agent_id, "settled": False},
    )
    session.add_all([identity, evaluation, reconciliation])
    session.flush()

    event = record_review_recovery(
        session,
        agent_identity_id=agent_id,
        source_policy_evaluation_id=evaluation_id,
        source_event_ids=[source_event_id],
    )

    assert event.metadata_["policy_version"] == G13_REVIEW_RECOVERY_POLICY_VERSION
    assert event.metadata_["canary_execution_limit"] == 1
    assert event.metadata_["concurrency_limit"] == 1
    assert validate_recovery_payload(event.metadata_) is True
    assert latest_operator_recovery(session, agent_id).event_id == event.event_id
