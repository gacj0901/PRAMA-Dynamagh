"""E3-A local epistemic policy specialization.

The policy consumes an explicit E1 snapshot. It never consumes Gamma as an
authority signal and it is not connected to acquisition, payment or PRAMA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.domain.mandates import EpistemicEvaluation
from app.policy_gate.substrate import PolicyEvaluationCore, PolicyInputTypeError, replay_policy


EPISTEMIC_DECISION_POLICY_V0_1 = "EPISTEMIC_DECISION_POLICY_V0_1"
EPISTEMIC_DECISION_POLICY_VERSION = "e3-a-epistemic-decision-v0.1"
EPISTEMIC_POLICY_TYPE = "EPISTEMIC_DECISION"
EPISTEMIC_RELATION_STATES = frozenset({"SATISFIES", "CONTRADICTS", "UNRESOLVED", "NOT_APPLICABLE"})
EPISTEMIC_STRUCTURAL_STATES = frozenset({"COMPLETE", "INCOMPLETE", "CONTRADICTED"})
DECISION_VOCABULARY = frozenset({"PERMIT", "REVIEW", "BLOCK"})
EPISTEMIC_POLICY_RULES = {
    "E1_REQUIRED_RELATIONS_COMPLETE": {
        "phenomenon": "all required E1 relations are satisfied",
        "input_fields": ["requirement_states", "relations", "structural_state", "evidence_ids"],
        "history": "one immutable E1 evaluation",
        "predicate": "structural_state == COMPLETE",
        "authority_consequence": "preserve the existing admissible path",
        "output": "PERMIT",
        "recovery": "not applicable; evaluate a later immutable snapshot",
        "falsification": "a COMPLETE snapshot must not produce a different existing Decision result",
    },
    "E1_REQUIRED_RELATION_UNRESOLVED": {
        "phenomenon": "a required E1 relation is unresolved",
        "input_fields": ["requirement_states", "structural_state"],
        "history": "one immutable E1 evaluation",
        "predicate": "structural_state == INCOMPLETE",
        "authority_consequence": "preserve the existing limited/review path",
        "output": "REVIEW",
        "recovery": "a later complete E1 snapshot may change the result",
        "falsification": "an INCOMPLETE snapshot must not produce PERMIT under the existing mapping",
    },
    "E1_REQUIRED_RELATION_CONTRADICTION": {
        "phenomenon": "a required E1 relation is contradicted",
        "input_fields": ["requirement_states", "relations", "structural_state"],
        "history": "one immutable E1 evaluation",
        "predicate": "structural_state == CONTRADICTED",
        "authority_consequence": "preserve the existing blocked path",
        "output": "BLOCK",
        "recovery": "a later non-contradicted E1 snapshot may change the result",
        "falsification": "a CONTRADICTED snapshot must not produce PERMIT under the existing mapping",
    },
}


@dataclass(frozen=True)
class EpistemicPolicyInput:
    """Explicit immutable policy input built from one E1 evaluation."""

    target_id: str
    evaluation_id: str
    evaluation_hash: str
    mandate_id: str
    trajectory_lineage_id: str | None
    semantic_version_tuple: tuple[str, ...]
    requirement_states: tuple[Mapping[str, Any], ...]
    relations: tuple[Mapping[str, Any], ...]
    structural_state: str
    evidence_ids: tuple[str, ...]
    omega: str | None = None
    expected_pv: str | None = None
    expected_ecm: str | None = None
    delta: str | None = None
    reference_gamma_hash: str | None = None
    gamma_formal_coordinates: Mapping[str, Any] | None = None

    @classmethod
    def from_evaluation(
        cls,
        evaluation: EpistemicEvaluation,
        *,
        trajectory_lineage_id: str | None = None,
        semantic_version_tuple: tuple[str, ...] | None = None,
        omega: str | None = None,
        expected_pv: str | None = None,
        expected_ecm: str | None = None,
        delta: str | None = None,
        reference_gamma_hash: str | None = None,
        gamma_formal_coordinates: Mapping[str, Any] | None = None,
    ) -> "EpistemicPolicyInput":
        relations = tuple(
            sorted(
                (dict(item) for item in evaluation.relations),
                key=lambda item: (str(item.get("requirement_id", "")), str(item.get("evidence_id", "")), str(item.get("relation_id", ""))),
            )
        )
        requirement_states = tuple(
            sorted((dict(item) for item in evaluation.requirement_states), key=lambda item: str(item.get("requirement_id", "")))
        )
        return cls(
            target_id=evaluation.target_id,
            evaluation_id=evaluation.evaluation_id,
            evaluation_hash=evaluation.canonical_hash,
            mandate_id=evaluation.mandate_id,
            trajectory_lineage_id=trajectory_lineage_id,
            semantic_version_tuple=semantic_version_tuple or (
                evaluation.observer_version,
                evaluation.contract_version,
                evaluation.algorithm_version,
            ),
            requirement_states=requirement_states,
            relations=relations,
            structural_state=evaluation.structural_state,
            evidence_ids=tuple(sorted(str(value) for value in evaluation.source_evidence_ids)),
            omega=omega,
            expected_pv=expected_pv,
            expected_ecm=expected_ecm,
            delta=delta,
            reference_gamma_hash=reference_gamma_hash,
            gamma_formal_coordinates=gamma_formal_coordinates,
        )

    @property
    def field_authority(self) -> dict[str, str]:
        authoritative = {
            "target_id", "evaluation_id", "evaluation_hash", "mandate_id",
            "trajectory_lineage_id", "semantic_version_tuple", "requirement_states",
            "relations", "structural_state", "evidence_ids",
        }
        diagnostic = {"omega", "expected_pv", "expected_ecm", "delta"}
        formal_only = {"reference_gamma_hash", "gamma_formal_coordinates"}
        return {
            **{name: "AUTHORITATIVE" for name in authoritative},
            **{name: "DIAGNOSTIC" for name in diagnostic},
            **{name: "FORMAL_ONLY" for name in formal_only},
        }

    def _relation_evidence(self, relation_ids: list[str]) -> list[str]:
        by_id = {str(item.get("relation_id")): str(item.get("evidence_id")) for item in self.relations}
        return sorted(by_id[item] for item in relation_ids if item in by_id)

    def canonical_core(self) -> dict[str, Any]:
        requirements: list[dict[str, Any]] = []
        for state in self.requirement_states:
            entry = dict(state)
            for key in (
                "supporting_relation_ids",
                "contradicting_relation_ids",
                "unresolved_relation_ids",
                "not_applicable_relation_ids",
            ):
                entry[f"{key.removesuffix('_relation_ids')}_evidence_ids"] = self._relation_evidence(list(entry.get(key, [])))
            requirements.append(entry)
        return {
            "input_contract": "e3-a-epistemic-policy-input-v0.1",
            "authority_classification": self.field_authority,
            "target_id": self.target_id,
            "evaluation_id": self.evaluation_id,
            "evaluation_hash": self.evaluation_hash,
            "mandate_id": self.mandate_id,
            "trajectory_lineage_id": self.trajectory_lineage_id,
            "semantic_version_tuple": list(self.semantic_version_tuple),
            "requirement_states": requirements,
            "relations": [dict(item) for item in self.relations],
            "structural_state": self.structural_state,
            "evidence_ids": list(self.evidence_ids),
            "diagnostic": {
                "omega": self.omega,
                "expected_pv": self.expected_pv,
                "expected_ecm": self.expected_ecm,
                "delta": self.delta,
            },
            "reference_gamma": {
                "hash": self.reference_gamma_hash,
                "formal_coordinates": dict(self.gamma_formal_coordinates or {}),
            },
        }


def evaluate_epistemic_policy(policy_input: EpistemicPolicyInput) -> PolicyEvaluationCore:
    """Apply only the existing structural Decision mapping.

    COMPLETE preserves the existing admissible path, INCOMPLETE preserves
    the existing limited/review path, and CONTRADICTED preserves the blocked
    path. Diagnostic and formal-only fields are deliberately ignored.
    """

    if policy_input.structural_state not in EPISTEMIC_STRUCTURAL_STATES:
        raise ValueError("EPISTEMIC_STRUCTURAL_STATE_UNSUPPORTED")
    for relation in policy_input.relations:
        if relation.get("relation_state") not in EPISTEMIC_RELATION_STATES:
            raise ValueError("EPISTEMIC_RELATION_STATE_UNSUPPORTED")

    if policy_input.structural_state == "COMPLETE":
        result, rule, legacy_reason = "PERMIT", "E1_REQUIRED_RELATIONS_COMPLETE", "ALL_REQUIRED_EVIDENCE_ADMITTED"
    elif policy_input.structural_state == "CONTRADICTED":
        result, rule, legacy_reason = "BLOCK", "E1_REQUIRED_RELATION_CONTRADICTION", "REQUIRED_EVIDENCE_REJECTED"
    else:
        result, rule, legacy_reason = "REVIEW", "E1_REQUIRED_RELATION_UNRESOLVED", "EVIDENCE_LIMITED"

    return PolicyEvaluationCore(
        policy_id=EPISTEMIC_DECISION_POLICY_V0_1,
        policy_version=EPISTEMIC_DECISION_POLICY_VERSION,
        policy_type=EPISTEMIC_POLICY_TYPE,
        policy_subject_type="EPISTEMIC_TARGET",
        policy_subject_id=policy_input.target_id,
        observation_refs=(policy_input.evaluation_id, *policy_input.evidence_ids),
        observation_contract_versions={"e1": policy_input.semantic_version_tuple[-2] if len(policy_input.semantic_version_tuple) >= 2 else "unknown"},
        input_core=policy_input.canonical_core(),
        triggered_rule_ids=(rule,),
        result=result,
        result_core={
            "decision_state": result,
            "reason_codes": [legacy_reason],
            "policy_rule_id": rule,
            "authoritative_fields": ["requirement_states", "relations", "structural_state", "evidence_ids"],
            "diagnostic_fields_ignored": ["omega", "expected_pv", "expected_ecm", "delta"],
            "formal_only_fields_ignored": ["reference_gamma_hash", "gamma_formal_coordinates"],
        },
    )


def replay_epistemic_policy(policy_input: EpistemicPolicyInput) -> PolicyEvaluationCore:
    computed = evaluate_epistemic_policy(policy_input)
    return replay_policy(computed, lambda: evaluate_epistemic_policy(policy_input))


def decision_input_topology(evaluation: PolicyEvaluationCore) -> dict[str, Any]:
    if evaluation.policy_type != EPISTEMIC_POLICY_TYPE:
        raise PolicyInputTypeError("POLICY_INPUT_TYPE_MISMATCH")
    return {
        "source": "O_EPISTEMIC",
        "policy": EPISTEMIC_DECISION_POLICY_V0_1,
        "authority": "AUTHORITATIVE_WHERE_JUSTIFIED",
        "policy_evaluation_id": evaluation.policy_evaluation_id,
        "input_hash": evaluation.input_hash,
    }


def gamma_input_topology() -> dict[str, Any]:
    return {
        "source": "O_EPISTEMIC_REFERENCE_PROJECTION",
        "contract": "O_EPI_PRAMA_PARTIAL_CORRESPONDENCE_V0_1",
        "role": "REFERENCE_DIAGNOSTIC",
        "authoritative_coordinates": [],
        "domain_interpretable_coordinates": ["Delta"],
        "formal_only_coordinates": ["delta_tilde", "Xi", "e", "A", "lambda", "Theta", "M", "G"],
    }
