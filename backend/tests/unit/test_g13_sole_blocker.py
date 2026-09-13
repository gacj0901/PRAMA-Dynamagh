"""Unit tests for sole_blocker metadata in G13 evaluations."""

from datetime import datetime, timedelta, timezone

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import (
    G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
    G13PolicyInput,
    evaluate_g13_policy,
)
from app.pramagraph.evaluation import digest


_NOW = datetime(2026, 9, 12, 0, 0, 0, tzinfo=timezone.utc)


def _observation(sequence: int, *, missing_data: tuple = (), failed: bool = False) -> OAgentObservation:
    lineage = OAgentSourceLineage(
        agent_identity_id="sole-blocker-agent",
        autonomy_run_ids=(f"run-{sequence}",),
    )
    facts = OAgentFacts(
        action_status="FAILED" if failed else "COMPLETED",
        local_decision_state="BLOCK" if failed else "PERMIT",
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code="GATEWAY_UNAVAILABLE" if failed else None,
        failure_event_types=("ACQUISITION_FAILED",) if failed else (),
        telegraph_statuses=("PAYMENT_UNCERTAIN",) if failed else ("SUCCEEDED",),
    )
    value = {
        "schema_version": "o-agent-v0",
        "observation_id": f"observation-{sequence}",
        "sequence": sequence,
        "observed_at": (_NOW + timedelta(seconds=sequence)).isoformat().replace("+00:00", "Z"),
        "timestamp_source": "created_at",
        "agent_identity_id": "sole-blocker-agent",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "AUTONOMY_RUN",
        "source_id": f"run-{sequence}",
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": list(missing_data),
    }
    return OAgentObservation(**value, content_hash=digest(value))


def test_sole_blocker_is_set_when_exactly_one_rule_triggers():
    obs = _observation(1, missing_data=("UNEXPECTED_CRITICAL_FIELD",))
    evaluation = evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "sole-blocker-agent",
            [obs],
            policy_version=G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
            expected_current_missing_codes=(),
        )
    )
    assert evaluation.result_core["sole_blocker"] == "G13_CURRENT_CRITICAL_OBSERVATION_MISSING"
    assert evaluation.result == "REVIEW"


def test_sole_blocker_is_none_when_multiple_rules_trigger():
    # Two failed executions trigger G13_REPEATED_EXECUTION_FAILURE in addition
    # to any missing-data rule, so triggered has more than one entry.
    obs1 = _observation(1, failed=True, missing_data=("X_MISSING",))
    obs2 = _observation(2, failed=True, missing_data=("X_MISSING",))
    evaluation = evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "sole-blocker-agent",
            [obs1, obs2],
            policy_version=G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
            expected_current_missing_codes=(),
        )
    )
    assert evaluation.result_core["sole_blocker"] is None


def test_sole_blocker_is_none_when_nothing_triggers():
    obs = _observation(1)
    evaluation = evaluate_g13_policy(
        G13PolicyInput.from_observations(
            "sole-blocker-agent",
            [obs],
            policy_version=G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
        )
    )
    assert evaluation.result_core["sole_blocker"] is None
    assert evaluation.result == "CONTINUE"
