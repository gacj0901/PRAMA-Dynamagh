"""Focused G13 v0.4 causal failure episode identity tests."""

from datetime import datetime, timezone, timedelta

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy, replay_g13_policy
from app.authority.recovery import (
    G13_REVIEW_RECOVERY_POLICY_VERSION,
    G13_REVIEW_RECOVERY_REASON,
    G13_REVIEW_RECOVERY_SCHEMA_VERSION,
)
from app.authority.autonomy import G13_OPERATOR_RECOVERY_POLICY_VERSION
from app.epistemic.contracts import canonical_hash
from app.pramagraph.evaluation import digest


AT = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _recovery() -> dict:
    material = {
        "schema_version": G13_REVIEW_RECOVERY_SCHEMA_VERSION,
        "agent_identity_id": "autonomy-controller",
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_REASON,
        "previous_policy_version": G13_OPERATOR_RECOVERY_POLICY_VERSION,
        "policy_version": G13_REVIEW_RECOVERY_POLICY_VERSION,
        "source_policy_evaluation_id": "review-evaluation-causal-identity",
        "source_event_ids": ["reconciliation-event-causal-identity"],
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": AT.isoformat().replace("+00:00", "Z"),
    }
    return {**material, "canonical_hash": canonical_hash(material), "recovery_event_id": "recovery-causal-identity"}


def _observation(sequence: int, *, episode: str | None, run_id: str, missing: tuple[str, ...] = ("EXTERNAL_RESULT_UNAVAILABLE",)) -> OAgentObservation:
    facts = OAgentFacts(
        action_status="FAILED",
        local_decision_state="PERMIT",
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code="TELEGRAPH_REQUEST_FAILED",
        failure_episode_id=episode,
        failure_event_types=("ACQUISITION_FAILED",),
        telegraph_statuses=("PAYMENT_UNCERTAIN",),
    )
    lineage = OAgentSourceLineage(agent_identity_id="autonomy-controller", autonomy_run_ids=(run_id,))
    payload = {
        "schema_version": "o-agent-v0",
        "observation_id": f"causal-observation-{sequence}",
        "sequence": sequence,
        "observed_at": (AT + timedelta(minutes=sequence)).isoformat().replace("+00:00", "Z"),
        "timestamp_source": "created_at",
        "agent_identity_id": "autonomy-controller",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "AUTONOMY_RUN",
        "source_id": run_id,
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": list(missing),
    }
    return OAgentObservation(**payload, content_hash=digest(payload))


def _evaluate(observations):
    return evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "autonomy-controller",
            observations,
            policy_version=G13_REVIEW_RECOVERY_POLICY_VERSION,
            operator_recovery=_recovery(),
            allow_sparse_window=True,
            expected_current_missing_codes=("EVIDENCE_NOT_PRESENT",),
        )
    )


def test_same_episode_multiple_events_and_runs_counts_once():
    result = _evaluate([
        _observation(1, episode="episode-a", run_id="run-a"),
        _observation(2, episode="episode-a", run_id="run-b"),
    ])
    assert result.result == "THROTTLE"
    assert result.result_core["distinct_external_dependency_count"] == 1


def test_three_distinct_episodes_escalate_to_review():
    result = _evaluate([_observation(i, episode=f"episode-{i}", run_id=f"run-{i}") for i in range(1, 4)])
    assert result.result == "REVIEW"
    assert result.result_core["distinct_external_dependency_count"] == 3


def test_mixed_duplicate_projections_count_three_episodes():
    episodes = ["episode-a", "episode-a", "episode-a", "episode-b", "episode-b", "episode-c", "episode-c", "episode-c", "episode-c"]
    result = _evaluate([_observation(i, episode=episode, run_id=f"run-{i}") for i, episode in enumerate(episodes, 1)])
    assert result.result == "REVIEW"
    assert result.result_core["distinct_external_dependency_count"] == 3


def test_same_provider_distinct_episodes_do_not_collapse():
    result = _evaluate([_observation(i, episode=f"telegraph-episode-{i}", run_id=f"run-{i}") for i in range(1, 4)])
    assert result.result_core["distinct_external_dependency_count"] == 3


def test_same_episode_retry_does_not_escalate():
    result = _evaluate([
        _observation(1, episode="retry-episode", run_id="run-1"),
        _observation(2, episode="retry-episode", run_id="run-2"),
        _observation(3, episode="retry-episode", run_id="run-3"),
    ])
    assert result.result == "THROTTLE"
    assert result.result_core["distinct_external_dependency_count"] == 1


def test_missing_episode_identity_never_permits_without_fresh_result_context():
    result = _evaluate([_observation(1, episode=None, run_id="run-missing", missing=())])
    assert result.result == "REVIEW"
    assert result.result_core["missing_failure_episode_identity_count"] == 1


def test_cross_agent_episode_observation_fails_closed():
    other = _observation(1, episode="episode-other", run_id="run-other").model_copy(
        update={"agent_identity_id": "different-agent"}
    )
    result = evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "autonomy-controller",
            [other],
            policy_version=G13_REVIEW_RECOVERY_POLICY_VERSION,
            operator_recovery=_recovery(),
            allow_sparse_window=True,
        )
    )
    assert result.result == "HALT"


def test_causal_episode_replay_is_deterministic():
    policy_input = G13PolicyInput.from_observations(
        "autonomy-controller",
        [
            _observation(1, episode="episode-a", run_id="run-a"),
            _observation(2, episode="episode-a", run_id="run-b"),
            _observation(3, episode="episode-b", run_id="run-c"),
        ],
        policy_version=G13_REVIEW_RECOVERY_POLICY_VERSION,
        operator_recovery=_recovery(),
        allow_sparse_window=True,
    )
    first = evaluate_g13_policy(policy_input)
    replayed = replay_g13_policy(policy_input)
    assert first.result == replayed.result == "THROTTLE"
    assert first.result_core["distinct_external_dependency_count"] == 2
    assert first.input_hash == replayed.input_hash
    assert first.result_hash == replayed.result_hash
