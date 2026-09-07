from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import update

from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy, pre_next_action_gate
from app.authority.epistemic import EpistemicPolicyInput, evaluate_epistemic_policy
from app.domain.mandates import EpistemicEvaluation, PolicyEvaluation
from app.policy_gate.substrate import persist_policy_evaluation


def _e1(target_id: str, evaluation_id: str) -> EpistemicEvaluation:
    return EpistemicEvaluation(
        evaluation_id=evaluation_id,
        mandate_id="authority-integration-mandate-" + target_id,
        target_id=target_id,
        evidence_set_hash="0x" + "1" * 64,
        requirement_states=[
            {
                "requirement_id": "req-" + target_id,
                "requirement_type": "asset_identity",
                "required": True,
                "state": "SATISFIED",
                "supporting_relation_ids": ["rel-" + target_id],
                "contradicting_relation_ids": [],
                "unresolved_relation_ids": [],
                "not_applicable_relation_ids": [],
            }
        ],
        relations=[
            {
                "relation_id": "rel-" + target_id,
                "requirement_id": "req-" + target_id,
                "evidence_id": "evidence-" + target_id,
                "relation_state": "SATISFIES",
                "relation_basis": {"rule": "fixture"},
                "canonical_hash": "0x" + "2" * 64,
            }
        ],
        contradictions=[],
        limitations=[],
        structural_state="COMPLETE",
        observer_version="O_EPISTEMIC-v0.1",
        contract_version="e1-c2-crypto-price-v0.1",
        algorithm_version="e1-c2-deterministic-relational-v0.1",
        source_evidence_ids=["evidence-" + target_id],
        canonical_hash="0x" + "3" * 64,
    )


def test_shared_policy_evaluation_is_idempotent_and_append_only(session):
    suffix = str(uuid.uuid4())
    epistemic = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(_e1("target-" + suffix, "eval-" + suffix)))
    first = persist_policy_evaluation(session, epistemic)
    session.flush()
    second = persist_policy_evaluation(session, epistemic)
    assert first.policy_evaluation_id == second.policy_evaluation_id
    assert session.query(PolicyEvaluation).filter_by(policy_evaluation_id=first.policy_evaluation_id).count() == 1

    with pytest.raises(Exception):
        session.execute(update(PolicyEvaluation).where(PolicyEvaluation.policy_evaluation_id == first.policy_evaluation_id).values(result="BLOCK"))
        session.flush()
    session.rollback()


def test_shared_substrate_keeps_g13_authority_separate_from_e1(session):
    suffix = str(uuid.uuid4())
    epistemic = evaluate_epistemic_policy(EpistemicPolicyInput.from_evaluation(_e1("target-" + suffix, "eval-" + suffix)))
    autonomy_input = G13PolicyInput.from_observations("agent-" + suffix, [])
    autonomy = evaluate_g13_policy(autonomy_input)
    assert epistemic.policy_type != autonomy.policy_type
    assert autonomy.result == "REVIEW"
    assert pre_next_action_gate(local_decision=epistemic.result, economic_authorized=True, longitudinal_result=autonomy.result)[0] is False
