"""Authority gate denials must not feed G13 execution-failure accounting.

A gate denial (G13_REVIEW, G13_HALT, G13_THROTTLE_CONSTRAINTS_REQUIRED) is an
outcome of *governance*, not an agent execution failure: the run was impeded
pre-network by the authority check and never performed external work.  These
tests pin the causal semantics:

* G13_REVIEW pre-network                     -> failure_count does NOT rise
* G13_THROTTLE_CONSTRAINTS_REQUIRED pre-net  -> failure_count does NOT rise
* two consecutive authority denials          -> NO G13_REPEATED_EXECUTION_FAILURE
* two real internal execution failures       -> YES G13_REPEATED_EXECUTION_FAILURE
* external dependency failure                -> preserved, not agent failure
"""

from datetime import datetime, timedelta, timezone

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import (
    G13_AUTHORITY_DENIAL_CODES,
    G13PolicyInput,
    evaluate_g13_policy,
)
from app.pramagraph.evaluation import digest

AT = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)


def _observation(
    sequence: int,
    run_id: str,
    *,
    failure_code: str | None = None,
    failure_event_types: tuple[str, ...] = (),
    telegraph_statuses: tuple[str, ...] = (),
    failure_episode_id: str | None = None,
    failure_episode_ids: tuple[str, ...] = (),
    action_status: str = "FAILED",
    local_decision_state: str | None = None,
    evidence_complete: bool = False,
    evaluation_complete: bool = False,
    decision_complete: bool = False,
    ticket_complete: bool = False,
    mandate_status: str | None = None,
    acquisition_statuses: tuple[str, ...] = (),
) -> OAgentObservation:
    agents = {
        "agent_identity_id": "autonomy-controller",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
    }
    facts = OAgentFacts(
        action_status=action_status,
        local_decision_state=local_decision_state,
        local_decision_scope="LOCAL_DECISION_ONLY" if local_decision_state else None,
        failure_code=failure_code,
        failure_event_types=failure_event_types,
        telegraph_statuses=telegraph_statuses,
        failure_episode_id=failure_episode_id,
        failure_episode_ids=failure_episode_ids,
        evidence_complete=evidence_complete,
        evaluation_complete=evaluation_complete,
        decision_complete=decision_complete,
        ticket_complete=ticket_complete,
        mandate_status=mandate_status,
        acquisition_statuses=acquisition_statuses,
    )
    lineage = OAgentSourceLineage(
        agent_identity_id="autonomy-controller",
        autonomy_run_ids=(run_id,),
    )
    payload = {
        "schema_version": "o-agent-v0",
        "observation_id": f"gate-denial-obs-{sequence}",
        "sequence": sequence,
        "observed_at": (AT + timedelta(minutes=sequence)).isoformat().replace("+00:00", "Z"),
        "timestamp_source": "created_at",
        **agents,
        "source_kind": "AUTONOMY_RUN",
        "source_id": run_id,
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
    }
    return OAgentObservation(**payload, content_hash=digest(payload))


def _evaluate(observations: list[OAgentObservation]):
    policy_input = G13PolicyInput.from_observations(
        "autonomy-controller",
        observations,
        trajectory_lineage_id="o-agent-v0:autonomy-controller",
        allow_sparse_window=True,
        expected_current_missing_codes=(
            "EVIDENCE_NOT_PRESENT",
            "EVALUATION_NOT_PRESENT",
            "LOCAL_DECISION_NOT_PRESENT",
            "TELEGRAPH_LATENCY_NOT_AVAILABLE",
            "TICKET_NOT_PRESENT",
        ),
    )
    return evaluate_g13_policy(policy_input)


def _authority_denial_obs(seq: int, run_id: str, code: str) -> OAgentObservation:
    """A run aborted pre-network by the authority gate: no telegraph work,
    no decision produced — only the denial failure_code."""
    return _observation(
        seq,
        run_id,
        failure_code=code,
        failure_event_types=(f"{code}_ABORTED",),
        telegraph_statuses=("NOT_EXECUTED",),
        action_status="FAILED",
    )


def test_g13_review_pre_network_does_not_increment_failure_count():
    observations = [_authority_denial_obs(1, "run-1", "G13_REVIEW")]
    result = _evaluate(observations)
    assert result.result_core.get("distinct_failure_count", 0) == 0
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids
    assert "G13_EXECUTION_FAILURE_DEGRADATION" not in result.triggered_rule_ids


def test_g13_throttle_constraints_pre_network_does_not_increment_failure_count():
    observations = [_authority_denial_obs(1, "run-1", "G13_THROTTLE_CONSTRAINTS_REQUIRED")]
    result = _evaluate(observations)
    assert result.result_core.get("distinct_failure_count", 0) == 0
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids


def test_two_consecutive_authority_denials_do_not_trigger_repeated_execution_failure():
    observations = [
        _authority_denial_obs(1, "run-1", "G13_REVIEW"),
        _authority_denial_obs(2, "run-2", "G13_HALT"),
    ]
    result = _evaluate(observations)
    assert result.result_core.get("distinct_failure_count", 0) == 0
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids


def test_g13_halt_is_an_authority_denial_code():
    assert "G13_HALT" in G13_AUTHORITY_DENIAL_CODES
    assert "G13_REVIEW" in G13_AUTHORITY_DENIAL_CODES
    assert "G13_THROTTLE_CONSTRAINTS_REQUIRED" in G13_AUTHORITY_DENIAL_CODES


def test_two_real_internal_execution_failures_still_trigger_repeated_failure():
    observations = [
        _observation(
            1,
            "run-1",
            failure_code="INTERNAL_RUNTIME_ERROR",
            failure_event_types=("ACQUISITION_FAILED",),
            telegraph_statuses=("FAILED",),
        ),
        _observation(
            2,
            "run-2",
            failure_code="INTERNAL_RUNTIME_ERROR",
            failure_event_types=("ACQUISITION_FAILED",),
            telegraph_statuses=("FAILED",),
        ),
    ]
    result = _evaluate(observations)
    assert result.result_core.get("distinct_failure_count", 0) == 2
    assert "G13_REPEATED_EXECUTION_FAILURE" in result.triggered_rule_ids


def test_external_dependency_failure_is_preserved_but_not_agent_execution_failure():
    observations = [
        _observation(
            1,
            "run-1",
            failure_code="TELEGRAPH_REQUEST_FAILED",
            failure_event_types=("ACQUISITION_FAILED",),
            telegraph_statuses=("FAILED",),
            failure_episode_id="ext-episode-1",
            failure_episode_ids=("ext-episode-1",),
        ),
        _observation(
            2,
            "run-2",
            failure_code="X402_FACILITATOR_TIMEOUT",
            failure_event_types=("ACQUISITION_FAILED",),
            telegraph_statuses=("FAILED",),
            failure_episode_id="ext-episode-2",
            failure_episode_ids=("ext-episode-2",),
        ),
    ]
    result = _evaluate(observations)
    # External dependency failures are excluded from the agent execution-failure
    # count, so they cannot produce G13_REPEATED_EXECUTION_FAILURE by themselves.
    assert result.result_core.get("distinct_failure_count", 0) == 0
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids


def test_authority_denial_does_not_mask_subsequent_real_failure():
    """A G13_REVIEW denial followed by a genuine internal failure: only the
    real failure may count."""
    observations = [
        _authority_denial_obs(1, "run-1", "G13_REVIEW"),
        _observation(
            2,
            "run-2",
            failure_code="INTERNAL_RUNTIME_ERROR",
            failure_event_types=("ACQUISITION_FAILED",),
            telegraph_statuses=("FAILED",),
        ),
    ]
    result = _evaluate(observations)
    assert result.result_core.get("distinct_failure_count", 0) == 1
    assert "G13_EXECUTION_FAILURE_DEGRADATION" in result.triggered_rule_ids
    assert "G13_REPEATED_EXECUTION_FAILURE" not in result.triggered_rule_ids
