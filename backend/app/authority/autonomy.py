"""G13-D/E longitudinal autonomy policy specialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from app.agents.observation import OAgentObservation, O_AGENT_SCHEMA_VERSION
from app.policy_gate.substrate import PolicyEvaluationCore, PolicyInputTypeError, replay_policy


G13_STRUCTURAL_AUTONOMY_POLICY_V0_1 = "G13_STRUCTURAL_AUTONOMY_POLICY_V0_1"
G13_STRUCTURAL_AUTONOMY_POLICY_V0_2 = "G13_STRUCTURAL_AUTONOMY_POLICY_V0_2"
G13_LEGACY_POLICY_VERSION = "g13-d-structural-autonomy-v0.1"
G13_STRUCTURAL_AUTONOMY_POLICY_VERSION = "g13-d-structural-autonomy-v0.2"
G13_SUPPORTED_POLICY_VERSIONS = frozenset({
    G13_LEGACY_POLICY_VERSION,
    G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
})
G13_POLICY_TYPE = "STRUCTURAL_AUTONOMY"
G13_OUTPUTS = frozenset({"CONTINUE", "THROTTLE", "REVIEW", "HALT"})
G13_PRECEDENCE = {"CONTINUE": 0, "THROTTLE": 1, "REVIEW": 2, "HALT": 3}
G13_RULES = {
    "G13_REQUIRED_TRAJECTORY_MISSING": {
        "phenomenon": "required ordered trajectory is unavailable",
        "input_fields": ["ordered_observations", "window_definition"],
        "history": "the supplied trajectory window",
        "predicate": "ordered_observations is empty",
        "authority_consequence": "autonomous continuation cannot be reconstructed",
        "output": "REVIEW",
        "recovery": "a later valid trajectory window",
        "falsification": "a valid non-empty window must not trigger this rule",
    },
    "G13_IDENTITY_OR_TRAJECTORY_INTEGRITY": {
        "phenomenon": "agent or trajectory identity integrity is violated",
        "input_fields": ["agent_id", "trajectory_lineage_id", "ordered_observations", "integrity_violations"],
        "history": "the supplied window",
        "predicate": "integrity_violations is non-empty",
        "authority_consequence": "identity-contaminated continuation is prohibited",
        "output": "HALT",
        "recovery": "operator review and a new valid window; no row mutation",
        "falsification": "cross-agent or conflicting duplicate input must never be accepted as CONTINUE",
    },
    "G13_CURRENT_CRITICAL_OBSERVATION_MISSING": {
        "phenomenon": "the latest observation explicitly carries missing data",
        "input_fields": ["ordered_observations", "missing_data"],
        "history": "latest supplied observation only",
        "predicate": "latest missing_data is non-empty",
        "authority_consequence": "current longitudinal state is not reconstructible",
        "output": "REVIEW",
        "recovery": "a later complete observation",
        "falsification": "a complete latest observation must not trigger this rule",
    },
    "G13_REPEATED_LOCAL_BLOCK": {
        "phenomenon": "repeated local Decision BLOCK observations",
        "input_fields": ["facts.local_decision_state"],
        "history": "the supplied ordered window",
        "predicate": "at least two BLOCK observations",
        "authority_consequence": "autonomous continuation requires review",
        "output": "REVIEW",
        "recovery": "a later window without the repeated degradation",
        "falsification": "one or zero BLOCK observations must not trigger this rule",
    },
    "G13_LOCAL_BLOCK_DEGRADATION": {
        "phenomenon": "one local Decision BLOCK observation",
        "input_fields": ["facts.local_decision_state"],
        "history": "the supplied ordered window",
        "predicate": "exactly one BLOCK observation",
        "authority_consequence": "continuation is permitted only under throttle constraints",
        "output": "THROTTLE",
        "recovery": "a later window without the degradation",
        "falsification": "zero BLOCK observations must not trigger this rule",
    },
    "G13_REPEATED_EXECUTION_FAILURE": {
        "phenomenon": "repeated persisted execution failures",
        "input_fields": ["facts.failure_code", "facts.failure_event_types"],
        "history": "the supplied ordered window",
        "predicate": "at least two failure-bearing observations",
        "authority_consequence": "autonomous continuation requires review",
        "output": "REVIEW",
        "recovery": "a later window without repeated failure",
        "falsification": "one or zero failure-bearing observations must not trigger this rule",
    },
    "G13_EXECUTION_FAILURE_DEGRADATION": {
        "phenomenon": "one persisted execution failure",
        "input_fields": ["facts.failure_code", "facts.failure_event_types"],
        "history": "the supplied ordered window",
        "predicate": "exactly one failure-bearing observation",
        "authority_consequence": "continuation is permitted only under throttle constraints",
        "output": "THROTTLE",
        "recovery": "a later window without the failure",
        "falsification": "zero failure-bearing observations must not trigger this rule",
    },
}


@dataclass(frozen=True)
class G13PolicyInput:
    agent_id: str
    trajectory_lineage_id: str
    observation_refs: tuple[str, ...]
    ordered_observations: tuple[Mapping[str, Any], ...]
    window_definition: Mapping[str, Any]
    o_agent_contract_version: str
    policy_version: str = G13_STRUCTURAL_AUTONOMY_POLICY_VERSION
    missing_data: tuple[str, ...] = ()
    integrity_violations: tuple[str, ...] = ()

    @classmethod
    def from_observations(
        cls,
        agent_id: str,
        observations: Iterable[OAgentObservation],
        *,
        trajectory_lineage_id: str | None = None,
        allow_sparse_window: bool = False,
        expected_current_missing_codes: Iterable[str] = (),
        policy_version: str = G13_STRUCTURAL_AUTONOMY_POLICY_VERSION,
    ) -> "G13PolicyInput":
        ordered = sorted(list(observations), key=lambda item: (item.sequence, item.observation_id))
        seen: dict[str, str] = {}
        integrity: set[str] = set()
        deduped: list[OAgentObservation] = []
        for item in ordered:
            if item.agent_identity_id != agent_id or item.source_lineage.agent_identity_id != agent_id:
                integrity.add("AGENT_IDENTITY_LINEAGE_MISMATCH")
            previous_hash = seen.get(item.observation_id)
            if previous_hash is not None:
                if previous_hash != item.content_hash:
                    integrity.add("DUPLICATE_OBSERVATION_HASH_CONFLICT")
                continue
            seen[item.observation_id] = item.content_hash
            deduped.append(item)
            if item.schema_version != O_AGENT_SCHEMA_VERSION:
                integrity.add("UNSUPPORTED_O_AGENT_VERSION")
        if not allow_sparse_window and any(item.sequence != index for index, item in enumerate(deduped, start=1)):
            integrity.add("TRAJECTORY_SEQUENCE_NOT_CONTIGUOUS")
        if trajectory_lineage_id is None:
            trajectory_lineage_id = f"{O_AGENT_SCHEMA_VERSION}:{agent_id}"
        payloads = tuple({**item.canonical_payload(), "content_hash": item.content_hash} for item in deduped)
        refs = tuple(item.observation_id for item in deduped)
        missing = tuple(sorted({code for item in deduped for code in item.missing_data}))
        return cls(
            agent_id=agent_id,
            trajectory_lineage_id=trajectory_lineage_id,
            observation_refs=refs,
            ordered_observations=payloads,
            window_definition={
                "kind": "ordered_o_agent_sparse_window" if allow_sparse_window else "ordered_o_agent_stream",
                "start_sequence": deduped[0].sequence if deduped else None,
                "end_sequence": deduped[-1].sequence if deduped else None,
                "source": "caller_supplied_observation_window",
                "expected_current_missing_codes": sorted(set(expected_current_missing_codes)),
            },
            o_agent_contract_version=O_AGENT_SCHEMA_VERSION,
            policy_version=policy_version,
            missing_data=missing,
            integrity_violations=tuple(sorted(integrity)),
        )

    def canonical_core(self) -> dict[str, Any]:
        return {
            "input_contract": (
                "g13-d-policy-input-v0.1"
                if self.policy_version == G13_LEGACY_POLICY_VERSION
                else "g13-d-policy-input-v0.2"
            ),
            "agent_id": self.agent_id,
            "trajectory_lineage_id": self.trajectory_lineage_id,
            "observation_refs": list(self.observation_refs),
            "ordered_observations": [dict(item) for item in self.ordered_observations],
            "window_definition": dict(self.window_definition),
            "o_agent_contract_version": self.o_agent_contract_version,
            "policy_version": self.policy_version,
            "missing_data": list(self.missing_data),
            "integrity_violations": list(self.integrity_violations),
        }


def _facts(input_value: G13PolicyInput) -> list[Mapping[str, Any]]:
    return [dict(item.get("facts") or {}) for item in input_value.ordered_observations]


def _distinct_execution_counts(policy_input: G13PolicyInput) -> tuple[int, int]:
    """Count causal executions, not every projection derived from one run.

    A G13-denied action persists a NOT_EXECUTED call for audit. It is excluded
    from degradation counts because treating the denial as a fresh execution
    failure would make recovery impossible. Legacy v0.1 replay keeps its exact
    observation-counting behavior.
    """
    units: dict[str, dict[str, bool]] = {}
    for item in policy_input.ordered_observations:
        facts = dict(item.get("facts") or {})
        lineage = dict(item.get("source_lineage") or {})
        run_ids = tuple(lineage.get("autonomy_run_ids") or ())
        unit_id = run_ids[0] if run_ids else str(item.get("observation_id"))
        statuses = set(facts.get("telegraph_statuses") or ())
        unit = units.setdefault(unit_id, {"block": False, "failure": False, "not_executed": False, "executed": False})
        unit["block"] = unit["block"] or facts.get("local_decision_state") == "BLOCK"
        unit["failure"] = unit["failure"] or bool(facts.get("failure_code") or facts.get("failure_event_types"))
        unit["not_executed"] = unit["not_executed"] or "NOT_EXECUTED" in statuses
        unit["executed"] = unit["executed"] or bool(statuses - {"NOT_EXECUTED", "REQUESTED"})
    eligible = [unit for unit in units.values() if unit["executed"] or not unit["not_executed"]]
    return (
        sum(1 for unit in eligible if unit["block"]),
        sum(1 for unit in eligible if unit["failure"]),
    )


def evaluate_g13_policy(policy_input: G13PolicyInput) -> PolicyEvaluationCore:
    if policy_input.policy_version not in G13_SUPPORTED_POLICY_VERSIONS:
        raise ValueError("G13_POLICY_VERSION_UNSUPPORTED")

    facts = _facts(policy_input)
    source_observations = policy_input.ordered_observations
    triggered: list[str] = []
    outcome = "CONTINUE"

    def trigger(rule_id: str, result: str) -> None:
        nonlocal outcome
        triggered.append(rule_id)
        if G13_PRECEDENCE[result] > G13_PRECEDENCE[outcome]:
            outcome = result

    if not source_observations:
        trigger("G13_REQUIRED_TRAJECTORY_MISSING", "REVIEW")
    if policy_input.integrity_violations:
        trigger("G13_IDENTITY_OR_TRAJECTORY_INTEGRITY", "HALT")

    # The latest explicitly supplied observation is the only source for a
    # current missing-data judgment; historical missing markers remain in the
    # input for audit and do not become a hidden score.
    expected_missing = set(policy_input.window_definition.get("expected_current_missing_codes") or ())
    current_missing = set(source_observations[-1].get("missing_data") or ()) if source_observations else set()
    if current_missing - expected_missing:
        trigger("G13_CURRENT_CRITICAL_OBSERVATION_MISSING", "REVIEW")

    if policy_input.policy_version == G13_LEGACY_POLICY_VERSION:
        block_count = sum(1 for item in facts if item.get("local_decision_state") == "BLOCK")
        failure_count = sum(1 for item in facts if item.get("failure_code") or item.get("failure_event_types"))
        policy_id = G13_STRUCTURAL_AUTONOMY_POLICY_V0_1
    else:
        block_count, failure_count = _distinct_execution_counts(policy_input)
        policy_id = G13_STRUCTURAL_AUTONOMY_POLICY_V0_2
    if block_count >= 2:
        trigger("G13_REPEATED_LOCAL_BLOCK", "REVIEW")
    elif block_count == 1:
        trigger("G13_LOCAL_BLOCK_DEGRADATION", "THROTTLE")
    if failure_count >= 2:
        trigger("G13_REPEATED_EXECUTION_FAILURE", "REVIEW")
    elif failure_count == 1:
        trigger("G13_EXECUTION_FAILURE_DEGRADATION", "THROTTLE")

    result_core: dict[str, Any] = {
        "autonomy_state": outcome,
        "rule_precedence": ["HALT", "REVIEW", "THROTTLE", "CONTINUE"],
        "recovery": "re-evaluate a later valid ordered window; no historical row is mutated",
    }
    if policy_input.policy_version != G13_LEGACY_POLICY_VERSION:
        result_core.update({
            "distinct_block_count": block_count,
            "distinct_failure_count": failure_count,
        })

    return PolicyEvaluationCore(
        policy_id=policy_id,
        policy_version=policy_input.policy_version,
        policy_type=G13_POLICY_TYPE,
        policy_subject_type="AGENT_IDENTITY",
        policy_subject_id=policy_input.agent_id,
        observation_refs=policy_input.observation_refs,
        observation_contract_versions={"o_agent": policy_input.o_agent_contract_version},
        input_core=policy_input.canonical_core(),
        triggered_rule_ids=tuple(triggered),
        result=outcome,
        result_core=result_core,
    )


def replay_g13_policy(policy_input: G13PolicyInput) -> PolicyEvaluationCore:
    computed = evaluate_g13_policy(policy_input)
    return replay_policy(computed, lambda: evaluate_g13_policy(policy_input))


def pre_next_action_gate(
    *,
    local_decision: str,
    economic_authorized: bool,
    longitudinal_result: str,
    throttled_constraints_satisfied: bool = False,
) -> tuple[bool, str]:
    """Compose independent authorities without allowing an override."""

    if local_decision != "PERMIT":
        return False, "LOCAL_EPISTEMIC_DENIAL"
    if not economic_authorized:
        return False, "G12_ECONOMIC_DENIAL"
    if longitudinal_result == "HALT":
        return False, "G13_HALT"
    if longitudinal_result == "REVIEW":
        return False, "G13_REVIEW"
    if longitudinal_result == "THROTTLE" and not throttled_constraints_satisfied:
        return False, "G13_THROTTLE_CONSTRAINTS_REQUIRED"
    if longitudinal_result not in G13_OUTPUTS:
        return False, "G13_RESULT_UNSUPPORTED"
    return True, "NEXT_ACTION_AUTHORIZED"


def assert_g13_policy_type(evaluation: PolicyEvaluationCore) -> None:
    if evaluation.policy_type != G13_POLICY_TYPE:
        raise PolicyInputTypeError("POLICY_INPUT_TYPE_MISMATCH")
