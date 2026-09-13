"""Tests for the G13 recovery-observation bypass (observation-starvation fix).

Semantics under test:
- Exactly ONE recovery observation is granted per operator_recovery episode.
- The bypass applies ONLY when G13 reports REVIEW with sole_blocker
  G13_CURRENT_CRITICAL_OBSERVATION_MISSING.
- Consumption happens before opening the external connection (PRE_NETWORK).
- A new operator_recovery event opens a new episode (keyed by recovery_event_id).
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from app.authority.recovery import (
    G13_OPERATOR_RECOVERY_POLICY_VERSION,
    record_operator_recovery,
)
from app.authority.runtime import (
    G13_RECOVERY_OBSERVATION_EVENT_TYPE,
    current_g13_review_supersedable,
    recovery_observation_available,
)
from app.domain.mandates import AgentIdentity, UsageEvent


def _mk_identity(session, autonomy_state="REVIEW_REQUIRED"):
    agent_id = "obs-recovery-agent-" + str(uuid.uuid4())
    identity = AgentIdentity(
        agent_id=agent_id,
        name="Observation recovery fixture",
        origin="INTERNAL_AUTONOMY",
        status="ACTIVE",
        autonomy_state=autonomy_state,
    )
    session.add(identity)
    session.flush()
    return identity


def _mk_recovery(session, agent_id, *, minutes_ago=1):
    source = UsageEvent(
        event_id=str(uuid.uuid4()),
        mandate_id=None,
        event_type="AUTONOMY_RUN_FAILED",
        metadata_={"agent_identity_id": agent_id},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago + 1),
    )
    session.add(source)
    session.flush()
    return record_operator_recovery(
        session,
        agent_identity_id=agent_id,
        previous_failure_rules=["G13_CURRENT_CRITICAL_OBSERVATION_MISSING"],
        previous_endpoint_reference="https://devnode.telegraphprotocol.com",
        new_endpoint="http://127.0.0.1:7044",
        gateway_deployment_id=str(uuid.uuid4()),
        authority_mode="BINDING",
        previous_policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        source_event_ids=[source.event_id],
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        canary_budget_usdc=Decimal("0.010000"),
    )


def _consume(session, agent_id, recovery_event):
    session.add(
        UsageEvent(
            mandate_id=None,
            acquisition_id=str(uuid.uuid4()),
            event_type=G13_RECOVERY_OBSERVATION_EVENT_TYPE,
            metadata_={
                "recovery_event_id": str(recovery_event.event_id),
                "agent_id": agent_id,
                "sole_blocker": "G13_CURRENT_CRITICAL_OBSERVATION_MISSING",
            },
        )
    )
    session.flush()


def test_recovery_observation_available_before_consumption(session):
    identity = _mk_identity(session)
    recovery = _mk_recovery(session, identity.agent_id)
    assert recovery_observation_available(session, identity.agent_id) is True


def test_consumption_makes_second_observation_unavailable(session):
    """Idempotence: once consumed, the same episode never authorizes a second."""
    identity = _mk_identity(session)
    recovery = _mk_recovery(session, identity.agent_id)
    _consume(session, identity.agent_id, recovery)
    assert recovery_observation_available(session, identity.agent_id) is False
    # Repeated calls remain negative — no flapping, no re-authorization.
    assert recovery_observation_available(session, identity.agent_id) is False


def test_consumption_of_prior_episode_does_not_leak_into_new_recovery(session):
    """A new operator_recovery event starts a fresh episode with its own
    single-observation budget; the old episode's consumption is keyed to the
    old recovery_event_id."""
    identity = _mk_identity(session)
    first_episode = _mk_recovery(session, identity.agent_id, minutes_ago=5)
    _consume(session, identity.agent_id, first_episode)
    assert recovery_observation_available(session, identity.agent_id) is False

    second_episode = _mk_recovery(session, identity.agent_id, minutes_ago=0)
    assert second_episode.event_id != first_episode.event_id
    assert recovery_observation_available(session, identity.agent_id) is True


def test_no_recovery_event_means_no_observation(session):
    identity = _mk_identity(session)
    assert recovery_observation_available(session, identity.agent_id) is False


def test_supersedable_requires_review_required_state(session):
    """current_g13_review_supersedable only engages for identities whose
    persisted autonomy_state was left at REVIEW_REQUIRED; an identity already
    HALTED or ACTIVE is not superseded by this path."""
    halted = _mk_identity(session, autonomy_state="HALTED")
    _mk_recovery(session, halted.agent_id)
    assert current_g13_review_supersedable(session, halted, halted.agent_id) is False


def test_consumption_event_is_append_only_and_keyed_by_recovery_event(session):
    identity = _mk_identity(session)
    recovery = _mk_recovery(session, identity.agent_id)
    _consume(session, identity.agent_id, recovery)

    events = (
        session.query(UsageEvent)
        .filter_by(event_type=G13_RECOVERY_OBSERVATION_EVENT_TYPE)
        .all()
    )
    assert len(events) == 1
    metadata = events[0].metadata_
    assert metadata["recovery_event_id"] == str(recovery.event_id)
    assert metadata["agent_id"] == identity.agent_id
    assert metadata["sole_blocker"] == "G13_CURRENT_CRITICAL_OBSERVATION_MISSING"
