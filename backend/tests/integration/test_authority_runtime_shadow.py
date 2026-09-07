from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import uuid

from app.authority.composition import AuthorityCompositionInput, evaluate_authority_composition, replay_authority_composition
from app.domain.mandates import PolicyEvaluation
from app.persistence.database import SessionLocal
from app.policy_gate.substrate import persist_policy_evaluation


def _value(suffix: str) -> AuthorityCompositionInput:
    return AuthorityCompositionInput(
        agent_id="agent-" + suffix,
        run_id="run-" + suffix,
        action_id="action-" + suffix,
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        applicability={"CD": "APPLICABLE", "G12": "APPLICABLE", "CDG": "APPLICABLE"},
        epistemic_result="PERMIT",
        epistemic_evaluation_id="e3-" + suffix,
        epistemic_result_hash="0x" + "1" * 64,
        g12_result="PERMIT",
        g12_input_hash="0x" + "2" * 64,
        longitudinal_result="CONTINUE",
        longitudinal_evaluation_id="g13-" + suffix,
        longitudinal_result_hash="0x" + "3" * 64,
        throttled_constraints_satisfied=False,
        current_runtime_action="CONTINUE_TO_GATEWAY",
    )


def test_shadow_composition_roundtrip_is_append_only_and_replayable(session):
    value = _value(uuid.uuid4().hex)
    core = evaluate_authority_composition(value)
    row = persist_policy_evaluation(session, core)
    session.commit()

    same = persist_policy_evaluation(session, core)
    replay = replay_authority_composition(value)

    assert same.policy_evaluation_id == row.policy_evaluation_id
    assert replay.input_hash == row.input_hash
    assert replay.result_hash == row.result_hash
    assert session.query(PolicyEvaluation).filter_by(policy_evaluation_id=row.policy_evaluation_id).count() == 1


def test_shadow_composition_concurrent_retries_converge():
    value = _value(uuid.uuid4().hex)
    core = evaluate_authority_composition(value)

    def persist_once() -> str:
        independent = SessionLocal()
        try:
            row = persist_policy_evaluation(independent, core)
            independent.commit()
            return row.policy_evaluation_id
        except Exception:
            independent.rollback()
            raise
        finally:
            independent.close()

    with ThreadPoolExecutor(max_workers=3) as workers:
        identities = list(workers.map(lambda _: persist_once(), range(3)))

    assert len(set(identities)) == 1
