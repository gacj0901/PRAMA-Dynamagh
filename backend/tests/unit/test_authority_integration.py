from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest

from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
from app.authority.autonomy import (
    G13_LEGACY_POLICY_VERSION,
    G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
    G13PolicyInput,
    evaluate_g13_policy,
    pre_next_action_gate,
    replay_g13_policy,
)
from app.authority.delegated import g12_check
from app.authority.epistemic import (
    EPISTEMIC_DECISION_POLICY_V0_1,
    EPISTEMIC_DECISION_POLICY_VERSION,
    EpistemicPolicyInput,
    evaluate_epistemic_policy,
    gamma_input_topology,
    replay_epistemic_policy,
)
from app.domain.mandates import EpistemicEvaluation
from app.pramagraph.evaluation import decide
from app.policy_gate.substrate import PolicyEvaluationCore, PolicyInputTypeError


def _e1(structural_state: str = "COMPLETE", *, gamma: dict | None = None) -> EpistemicEvaluation:
    relation = {
        "relation_id": "rel-1",
        "requirement_id": "req-1",
        "evidence_id": "ev-1",
        "relation_state": "SATISFIES",
        "relation_basis": {"rule": "exact_field_match"},
        "canonical_hash": "0x" + "1" * 64,
    }
    return EpistemicEvaluation(
        evaluation_id="eval-1",
        mandate_id="mandate-1",
        target_id="target-1",
        evidence_set_hash="0x" + "2" * 64,
        requirement_states=[
            {
                "requirement_id": "req-1",
                "requirement_type": "asset_identity",
                "required": True,
                "state": "SATISFIED" if structural_state == "COMPLETE" else "UNRESOLVED",
                "supporting_relation_ids": ["rel-1"] if structural_state == "COMPLETE" else [],
                "contradicting_relation_ids": [],
                "unresolved_relation_ids": ["rel-1"] if structural_state == "INCOMPLETE" else [],
                "not_applicable_relation_ids": [],
            }
        ],
        relations=[relation],
        contradictions=[],
        limitations=[],
        structural_state=structural_state,
        observer_version="O_EPISTEMIC-v0.1",
        contract_version="e1-c2-crypto-price-v0.1",
        algorithm_version="e1-c2-deterministic-relational-v0.1",
        source_evidence_ids=["ev-1"],
        canonical_hash="0x" + "3" * 64,
    )


def _observation(agent_id: str, sequence: int, *, decision: str | None = "PERMIT", failure: str | None = None,
                 failure_events: tuple[str, ...] = (), telegraph_statuses: tuple[str, ...] = (),
                 run_id: str | None = None, missing: tuple[str, ...] = ()) -> OAgentObservation:
    lineage = OAgentSourceLineage(
        agent_identity_id=agent_id,
        mandate_ids=(f"m-{sequence}",),
        autonomy_run_ids=(run_id,) if run_id else (),
    )
    facts = OAgentFacts(
        action_status="TICKETED",
        local_decision_state=decision,
        local_decision_scope="LOCAL_DECISION_ONLY" if decision else None,
        failure_code=failure,
        failure_event_types=failure_events,
        telegraph_statuses=telegraph_statuses,
    )
    value = {
        "schema_version": "o-agent-v0",
        "observation_id": f"obs-{sequence}",
        "sequence": sequence,
        "observed_at": f"2026-09-06T10:0{sequence}:00Z",
        "timestamp_source": "created_at",
        "agent_identity_id": agent_id,
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "DECISION",
        "source_id": f"d-{sequence}",
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
        "missing_data": list(missing),
    }
    from app.pramagraph.evaluation import digest

    return OAgentObservation(**value, content_hash=digest(value))


def test_epistemic_input_is_explicit_and_gamma_is_non_authoritative():
    policy_input = EpistemicPolicyInput.from_evaluation(
        _e1(),
        omega="0.8",
        expected_pv="0.2",
        expected_ecm="0.3",
        delta="0.5",
        reference_gamma_hash="0x" + "4" * 64,
        gamma_formal_coordinates={"Xi": 999, "lambda": 0.1},
    )
    result = evaluate_epistemic_policy(policy_input)
    assert result.policy_id == EPISTEMIC_DECISION_POLICY_V0_1
    assert result.policy_version == EPISTEMIC_DECISION_POLICY_VERSION
    assert result.result == "PERMIT"
    assert result.input_core["authority_classification"]["structural_state"] == "AUTHORITATIVE"
    assert result.input_core["authority_classification"]["omega"] == "DIAGNOSTIC"
    assert result.input_core["authority_classification"]["gamma_formal_coordinates"] == "FORMAL_ONLY"
    changed_gamma = EpistemicPolicyInput.from_evaluation(_e1(), gamma_formal_coordinates={"Xi": -1})
    assert evaluate_epistemic_policy(changed_gamma).result == result.result
    assert gamma_input_topology()["authoritative_coordinates"] == []


@pytest.mark.parametrize(
    ("state", "decision"),
    [("COMPLETE", "PERMIT"), ("INCOMPLETE", "REVIEW"), ("CONTRADICTED", "BLOCK")],
)
def test_epistemic_policy_preserves_existing_decision_mapping(state, decision):
    assert evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(_e1(state))).result == decision


@pytest.mark.parametrize(
    ("e1_state", "legacy_state"),
    [
        ("COMPLETE", "STRUCTURALLY_ADMISSIBLE"),
        ("INCOMPLETE", "STRUCTURALLY_LIMITED"),
        ("CONTRADICTED", "STRUCTURALLY_BLOCKED"),
    ],
)
def test_e3a_policy_matches_authoritative_cd_for_all_existing_states(e1_state, legacy_state):
    old_result, old_reasons = decide(legacy_state)
    new = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(_e1(e1_state)))
    assert new.result == old_result
    assert new.result_core["reason_codes"] == old_reasons


def test_epistemic_policy_replay_and_policy_version_are_deterministic():
    value = EpistemicPolicyInput.from_evaluation(_e1())
    first = evaluate_epistemic_policy(value)
    second = replay_epistemic_policy(value)
    assert first.input_hash == second.input_hash
    assert first.result_hash == second.result_hash
    assert first.replay_identity == second.replay_identity
    assert first.policy_evaluation_id == second.policy_evaluation_id


def test_policy_substrate_rejects_cross_policy_type_confusion():
    value = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(_e1()))
    with pytest.raises(PolicyInputTypeError):
        from app.authority.autonomy import assert_g13_policy_type

        assert_g13_policy_type(value)


def test_g13_benign_repeated_degradation_and_replay():
    benign = G13PolicyInput.from_observations("agent-1", [_observation("agent-1", 1)])
    assert evaluate_g13_policy(benign).result == "CONTINUE"
    degraded = G13PolicyInput.from_observations(
        "agent-1",
        [_observation("agent-1", 1, decision="BLOCK"), _observation("agent-1", 2, failure="TIMEOUT")],
    )
    first = evaluate_g13_policy(degraded)
    assert first.result == "THROTTLE"
    repeated = G13PolicyInput.from_observations(
        "agent-1",
        [_observation("agent-1", 1, decision="BLOCK"), _observation("agent-1", 2, decision="BLOCK")],
    )
    assert evaluate_g13_policy(repeated).result == "REVIEW"
    replay = replay_g13_policy(repeated)
    assert replay.input_hash == evaluate_g13_policy(repeated).input_hash
    assert replay.result_hash == evaluate_g13_policy(repeated).result_hash


def test_g13_counts_distinct_executions_and_ignores_its_own_denials():
    first_attempt = [
        _observation("agent-1", 1, run_id="run-1", decision="BLOCK", failure="TIMEOUT", telegraph_statuses=("PAYMENT_UNCERTAIN",)),
        _observation("agent-1", 2, run_id="run-1", decision="BLOCK", failure_events=("ACQUISITION_FAILED",), telegraph_statuses=("PAYMENT_UNCERTAIN",)),
    ]
    denied_retry = _observation(
        "agent-1", 3, run_id="run-2", decision="BLOCK",
        failure_events=("ACQUISITION_FAILED",), telegraph_statuses=("NOT_EXECUTED",),
    )
    result = evaluate_g13_policy(G13PolicyInput.from_observations("agent-1", [*first_attempt, denied_retry]))
    assert result.result == "THROTTLE"
    assert result.result_core["distinct_failure_count"] == 1
    assert result.result_core["distinct_block_count"] == 1

    second_attempt = _observation(
        "agent-1", 4, run_id="run-3", decision="BLOCK",
        failure="TIMEOUT", telegraph_statuses=("PAYMENT_UNCERTAIN",),
    )
    assert evaluate_g13_policy(
        G13PolicyInput.from_observations("agent-1", [*first_attempt, denied_retry, second_attempt])
    ).result == "REVIEW"

    legacy = G13PolicyInput.from_observations(
        "agent-1", first_attempt, policy_version=G13_LEGACY_POLICY_VERSION,
    )
    legacy_result = evaluate_g13_policy(legacy)
    assert legacy_result.result == "REVIEW"
    assert legacy_result.policy_version == G13_LEGACY_POLICY_VERSION
    assert "distinct_failure_count" not in legacy_result.result_core
    assert legacy_result.result_hash == evaluate_g13_policy(legacy).result_hash


def test_g13_missing_identity_version_and_duplicate_conflict_fail_closed():
    assert evaluate_g13_policy(G13PolicyInput.from_observations("agent-1", [])).result == "REVIEW"
    other = _observation("agent-2", 1)
    assert evaluate_g13_policy(G13PolicyInput.from_observations("agent-1", [other])).result == "HALT"
    duplicate = _observation("agent-1", 1)
    conflicting = duplicate.model_copy(update={"content_hash": "0x" + "f" * 64})
    assert evaluate_g13_policy(G13PolicyInput.from_observations("agent-1", [duplicate, conflicting])).result == "HALT"


def test_g13_version_mismatch_is_not_silently_accepted():
    value = G13PolicyInput.from_observations("agent-1", [_observation("agent-1", 1)])
    with pytest.raises(ValueError, match="G13_POLICY_VERSION_UNSUPPORTED"):
        evaluate_g13_policy(value.__class__(**{**value.__dict__, "policy_version": "g13-d-structural-autonomy-v9"}))


def test_g13_explicit_sparse_recovery_window_preserves_original_sequences():
    observations = [_observation("agent-1", 2), _observation("agent-1", 9)]
    strict = G13PolicyInput.from_observations("agent-1", observations)
    assert evaluate_g13_policy(strict).result == "HALT"
    recovery = G13PolicyInput.from_observations(
        "agent-1", observations, allow_sparse_window=True,
        expected_current_missing_codes=("EXPECTED_AT_PRE_ACTION",),
    )
    assert evaluate_g13_policy(recovery).result == "CONTINUE"
    assert recovery.window_definition["start_sequence"] == 2
    assert recovery.window_definition["end_sequence"] == 9
    assert recovery.ordered_observations[-1]["sequence"] == 9


def test_profile_without_own_budget_still_requires_g12_reservation():
    class Profile:
        unlimited_budget = True
        economic_budget = None
        per_action_budget = None

    assert g12_check(Profile(), Decimal("0.01")) == (False, "G12_RESERVATION_REQUIRED")
    assert g12_check(Profile(), Decimal("0.01"), reservation_verified=True) == (True, "PERMIT")


@pytest.mark.parametrize(
    ("local", "economic", "longitudinal", "throttled", "allowed"),
    [
        ("PERMIT", True, "CONTINUE", False, True),
        ("PERMIT", True, "THROTTLE", False, False),
        ("PERMIT", True, "THROTTLE", True, True),
        ("PERMIT", True, "REVIEW", True, False),
        ("PERMIT", True, "HALT", True, False),
        ("BLOCK", True, "CONTINUE", True, False),
        ("PERMIT", False, "CONTINUE", True, False),
    ],
)
def test_pre_next_action_gate_composes_independent_authorities(local, economic, longitudinal, throttled, allowed):
    result, _reason = pre_next_action_gate(
        local_decision=local,
        economic_authorized=economic,
        longitudinal_result=longitudinal,
        throttled_constraints_satisfied=throttled,
    )
    assert result is allowed


def test_g13_contract_version_is_frozen():
    assert G13_STRUCTURAL_AUTONOMY_POLICY_VERSION == "g13-d-structural-autonomy-v0.2"
