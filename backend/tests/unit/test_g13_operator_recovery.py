from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority import runtime
from app.authority.autonomy import (
    G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
    G13PolicyInput,
    evaluate_g13_policy,
    replay_g13_policy,
)
from app.authority.recovery import (
    G13_OPERATOR_RECOVERY_POLICY_VERSION,
    G13_RECOVERY_EVENT_SCHEMA_VERSION,
    validate_recovery_payload,
)
from app.epistemic.contracts import canonical_hash
from app.pramagraph.evaluation import digest


RECOVERY_AT = datetime(2026, 9, 9, 6, 14, 30, tzinfo=timezone.utc)


def _recovery() -> dict:
    material = {
        "schema_version": G13_RECOVERY_EVENT_SCHEMA_VERSION,
        "agent_identity_id": "autonomy-controller",
        "operator_reviewed": True,
        "recovery_reason": "TELEGRAPH_ENDPOINT_CORRECTION",
        "previous_failure_rules": ["G13_REPEATED_EXECUTION_FAILURE", "G13_REPEATED_LOCAL_BLOCK"],
        "previous_endpoint_reference": "https://devnode.telegraphprotocol.com",
        "new_endpoint": "http://13.237.89.59:7044",
        "gateway_deployment_id": "72afe908-bd36-42a2-8df0-0cff751054f3",
        "authority_mode": "BINDING",
        "previous_policy_version": G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
        "policy_version": G13_OPERATOR_RECOVERY_POLICY_VERSION,
        "source_event_ids": ["failure-event-1", "failure-event-2"],
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "created_at": RECOVERY_AT.isoformat().replace("+00:00", "Z"),
    }
    return {
        **material,
        "canonical_hash": canonical_hash(material),
        "recovery_event_id": "recovery-event-1",
    }


def _observation(
    sequence: int,
    run_id: str,
    when: datetime,
    *,
    failed: bool,
    missing_data: tuple[str, ...] = (),
    telegraph_status: str | None = None,
) -> OAgentObservation:
    lineage = OAgentSourceLineage(agent_identity_id="autonomy-controller", autonomy_run_ids=(run_id,))
    facts = OAgentFacts(
        action_status="FAILED" if failed else "COMPLETED",
        local_decision_state="BLOCK" if failed else "PERMIT",
        local_decision_scope="LOCAL_DECISION_ONLY",
        failure_code="GATEWAY_UNAVAILABLE" if failed else None,
        failure_event_types=("ACQUISITION_FAILED",) if failed else (),
        telegraph_statuses=(telegraph_status,) if telegraph_status else ("PAYMENT_UNCERTAIN",) if failed else ("SUCCEEDED",),
    )
    value = {
        "schema_version": "o-agent-v0",
        "observation_id": f"observation-{sequence}",
        "sequence": sequence,
        "observed_at": when.isoformat().replace("+00:00", "Z"),
        "timestamp_source": "created_at",
        "agent_identity_id": "autonomy-controller",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "AUTONOMY_RUN",
        "source_id": run_id,
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": list(missing_data),
    }
    return OAgentObservation(**value, content_hash=digest(value))


def test_operator_recovery_allows_one_bounded_canary_and_then_continues():
    recovery = _recovery()
    canary = G13PolicyInput.from_observations(
        "autonomy-controller",
        [],
        policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        operator_recovery=recovery,
    )
    result = evaluate_g13_policy(canary)
    assert result.result == "THROTTLE"
    assert result.triggered_rule_ids == ("G13_OPERATOR_RECOVERY_CANARY",)
    assert result.result_core["operator_recovery_canary"] is True
    assert replay_g13_policy(canary).result_hash == result.result_hash

    completed = G13PolicyInput.from_observations(
        "autonomy-controller",
        [_observation(1, "post-recovery-run", RECOVERY_AT + timedelta(seconds=10), failed=False)],
        policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        operator_recovery=recovery,
    )
    after = evaluate_g13_policy(completed)
    assert after.result == "CONTINUE"
    assert after.result_core["post_recovery_execution_count"] == 1
    assert after.result_core["operator_recovery_canary"] is False


def test_invalid_recovery_fails_closed():
    recovery = {**_recovery(), "canonical_hash": "0x" + "0" * 64}
    assert validate_recovery_payload(recovery) is False
    value = G13PolicyInput.from_observations(
        "autonomy-controller",
        [],
        policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        operator_recovery=recovery,
    )
    result = evaluate_g13_policy(value)
    assert result.result == "HALT"
    assert "G13_IDENTITY_OR_TRAJECTORY_INTEGRITY" in result.triggered_rule_ids


def test_v02_replay_material_is_unchanged_by_recovery_extension():
    observations = [
        _observation(1, "failed-1", RECOVERY_AT - timedelta(minutes=2), failed=True),
        _observation(2, "failed-2", RECOVERY_AT - timedelta(minutes=1), failed=True),
    ]
    historical = G13PolicyInput.from_observations("autonomy-controller", observations)
    with_ignored_extension = G13PolicyInput.from_observations(
        "autonomy-controller",
        observations,
        policy_version=G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
        operator_recovery=_recovery(),
    )
    first = evaluate_g13_policy(historical)
    second = replay_g13_policy(with_ignored_extension)
    assert first.result == "REVIEW"
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash
    assert "operator_recovery" not in second.input_core


def test_runtime_uses_only_post_recovery_trajectory(monkeypatch):
    old = [
        _observation(1, "failed-1", RECOVERY_AT - timedelta(minutes=2), failed=True),
        _observation(2, "failed-2", RECOVERY_AT - timedelta(minutes=1), failed=True),
    ]
    recovery = _recovery()
    monkeypatch.setattr(runtime, "build_o_agent_stream", lambda *args: old)
    monkeypatch.setattr(
        runtime,
        "latest_operator_recovery",
        lambda *args: SimpleNamespace(
            metadata_={key: value for key, value in recovery.items() if key != "recovery_event_id"},
            event_id="recovery-event-1",
            created_at=RECOVERY_AT,
        ),
    )
    result = runtime.evaluate_current_g13(object(), "autonomy-controller")
    assert result.policy_version == G13_OPERATOR_RECOVERY_POLICY_VERSION
    assert result.result == "THROTTLE"
    assert result.result_core["distinct_failure_count"] == 0


def test_not_executed_recovery_observation_does_not_retrigger_missing_review():
    recovery = _recovery()
    denied = _observation(
        1,
        "denied-recovery-canary",
        RECOVERY_AT + timedelta(seconds=10),
        failed=False,
        missing_data=("UNEXPECTED_MISSING_RESULT",),
        telegraph_status="NOT_EXECUTED",
    )
    value = G13PolicyInput.from_observations(
        "autonomy-controller",
        [denied],
        policy_version=G13_OPERATOR_RECOVERY_POLICY_VERSION,
        operator_recovery=recovery,
        expected_current_missing_codes=(),
    )

    result = evaluate_g13_policy(value)

    assert result.result == "THROTTLE"
    assert result.triggered_rule_ids == ("G13_OPERATOR_RECOVERY_CANARY",)
