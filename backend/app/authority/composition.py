"""Authority composition helpers for the pre-next-action boundary.

The composition is an explicit policy evaluation of independent authority
inputs.  Binding callers consume the result before external action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.authority.autonomy import pre_next_action_gate
from app.policy_gate.substrate import PolicyEvaluationCore, replay_policy


AUTHORITY_COMPOSITION_POLICY_V0_1 = "AUTHORITY_COMPOSITION_POLICY_V0_1"
AUTHORITY_COMPOSITION_POLICY_VERSION = "authority-composition-shadow-v0.1"
AUTHORITY_COMPOSITION_POLICY_TYPE = "AUTHORITY_COMPOSITION"
AUTHORITY_COMPOSITION_OUTPUTS = frozenset({"ALLOW", "RESTRICT"})


@dataclass(frozen=True)
class AuthorityCompositionInput:
    """Canonical input for one pre-next-action shadow checkpoint."""

    agent_id: str
    run_id: str
    action_id: str
    action_kind: str
    applicability: Mapping[str, str]
    epistemic_result: str
    epistemic_evaluation_id: str | None
    epistemic_result_hash: str | None
    g12_result: str
    g12_input_hash: str | None
    longitudinal_result: str
    longitudinal_evaluation_id: str
    longitudinal_result_hash: str
    throttled_constraints_satisfied: bool
    current_runtime_action: str
    recovery_probe_authorized: bool = False
    shadow_mode: bool = True
    policy_version: str = AUTHORITY_COMPOSITION_POLICY_VERSION

    def canonical_core(self) -> dict[str, Any]:
        return {
            "input_contract": "authority-composition-input-v0.1",
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "applicability": dict(sorted(self.applicability.items())),
            "epistemic": {
                "result": self.epistemic_result,
                "evaluation_id": self.epistemic_evaluation_id,
                "result_hash": self.epistemic_result_hash,
            },
            "g12": {
                "result": self.g12_result,
                "input_hash": self.g12_input_hash,
            },
            "longitudinal": {
                "result": self.longitudinal_result,
                "evaluation_id": self.longitudinal_evaluation_id,
                "result_hash": self.longitudinal_result_hash,
            },
            "throttled_constraints_satisfied": self.throttled_constraints_satisfied,
            "recovery_probe_authorized": self.recovery_probe_authorized,
            "current_runtime_action": self.current_runtime_action,
            "shadow_mode": self.shadow_mode,
            "policy_version": self.policy_version,
        }


def evaluate_authority_composition(value: AuthorityCompositionInput) -> PolicyEvaluationCore:
    if value.policy_version != AUTHORITY_COMPOSITION_POLICY_VERSION:
        raise ValueError("AUTHORITY_COMPOSITION_POLICY_VERSION_UNSUPPORTED")
    if value.g12_result not in {"PERMIT", "DENY"}:
        raise ValueError("G12_RESULT_UNSUPPORTED")
    if value.epistemic_result not in {"PERMIT", "REVIEW", "BLOCK"}:
        raise ValueError("EPISTEMIC_RESULT_UNSUPPORTED")

    allowed, reason = pre_next_action_gate(
        local_decision=value.epistemic_result,
        economic_authorized=value.g12_result == "PERMIT",
        longitudinal_result=value.longitudinal_result,
        throttled_constraints_satisfied=value.throttled_constraints_satisfied,
        recovery_probe_authorized=value.recovery_probe_authorized,
    )
    output = "ALLOW" if allowed else "RESTRICT"
    runtime_allows = value.current_runtime_action in {"CONTINUE", "CONTINUE_TO_GATEWAY", "EXECUTE"}
    return PolicyEvaluationCore(
        policy_id=AUTHORITY_COMPOSITION_POLICY_V0_1,
        policy_version=value.policy_version,
        policy_type=AUTHORITY_COMPOSITION_POLICY_TYPE,
        policy_subject_type="AUTONOMY_ACTION",
        policy_subject_id=value.action_id,
        observation_refs=tuple(
            item for item in (
                value.action_id,
                value.epistemic_evaluation_id,
                value.longitudinal_evaluation_id,
            ) if item
        ),
        observation_contract_versions={
            "composition": value.policy_version,
            "g13": "g13-d-structural-autonomy-v0.1",
            "o_agent": "o-agent-v0",
        },
        input_core=value.canonical_core(),
        triggered_rule_ids=(reason,),
        result=output,
        result_core={
            "composed_state": output,
            "authority_reason": reason,
            "would_allow_next_action": allowed,
            "current_runtime_action": value.current_runtime_action,
            "shadow_divergence": runtime_allows != allowed,
            "authority_families": ["CD", "G12", "CDG"],
            "enforcement": "SHADOW_ONLY" if value.shadow_mode else "BINDING",
        },
    )


def replay_authority_composition(value: AuthorityCompositionInput) -> PolicyEvaluationCore:
    computed = evaluate_authority_composition(value)
    return replay_policy(computed, lambda: evaluate_authority_composition(value))

__all__ = [
    "AUTHORITY_COMPOSITION_POLICY_V0_1",
    "AUTHORITY_COMPOSITION_POLICY_VERSION",
    "AUTHORITY_COMPOSITION_POLICY_TYPE",
    "AuthorityCompositionInput",
    "evaluate_authority_composition",
    "replay_authority_composition",
    "pre_next_action_gate",
]
