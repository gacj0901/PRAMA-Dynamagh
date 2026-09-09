from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from app.agents.observation import build_o_agent_stream
from app.authority.recovery import (
    G13_RECOVERY_EVENT_TYPE,
    latest_operator_recovery,
    record_operator_recovery,
    validate_recovery_payload,
)
from app.domain.mandates import AgentIdentity, UsageEvent


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
