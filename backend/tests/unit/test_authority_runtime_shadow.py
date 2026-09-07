from __future__ import annotations

from dataclasses import replace

import pytest

from app.authority.composition import (
    AUTHORITY_COMPOSITION_POLICY_TYPE,
    AuthorityCompositionInput,
    evaluate_authority_composition,
    replay_authority_composition,
)


def _input(
    *,
    cd: str = "PERMIT",
    g12: str = "PERMIT",
    cdg: str = "CONTINUE",
    action: str = "CONTINUE_TO_GATEWAY",
    cd_applicability: str = "APPLICABLE",
    throttled: bool = False,
) -> AuthorityCompositionInput:
    return AuthorityCompositionInput(
        agent_id="agent-runtime",
        run_id="run-runtime",
        action_id="acquisition-runtime",
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        applicability={"CD": cd_applicability, "G12": "APPLICABLE", "CDG": "APPLICABLE"},
        epistemic_result=cd,
        epistemic_evaluation_id="e3-runtime" if cd_applicability == "APPLICABLE" else None,
        epistemic_result_hash="0x" + "1" * 64 if cd_applicability == "APPLICABLE" else None,
        g12_result=g12,
        g12_input_hash="0x" + "2" * 64,
        longitudinal_result=cdg,
        longitudinal_evaluation_id="g13-runtime",
        longitudinal_result_hash="0x" + "3" * 64,
        throttled_constraints_satisfied=throttled,
        current_runtime_action=action,
    )


@pytest.mark.parametrize(
    ("cd", "g12", "cdg", "expected", "reason"),
    [
        ("PERMIT", "PERMIT", "CONTINUE", "ALLOW", "NEXT_ACTION_AUTHORIZED"),
        ("BLOCK", "PERMIT", "CONTINUE", "RESTRICT", "LOCAL_EPISTEMIC_DENIAL"),
        ("PERMIT", "DENY", "CONTINUE", "RESTRICT", "G12_ECONOMIC_DENIAL"),
        ("PERMIT", "PERMIT", "HALT", "RESTRICT", "G13_HALT"),
    ],
)
def test_shadow_composition_preserves_conjunctive_authority(cd, g12, cdg, expected, reason):
    result = evaluate_authority_composition(_input(cd=cd, g12=g12, cdg=cdg))

    assert result.policy_type == AUTHORITY_COMPOSITION_POLICY_TYPE
    assert result.result == expected
    assert result.result_core["authority_reason"] == reason
    assert result.result_core["enforcement"] == "SHADOW_ONLY"


def test_missing_longitudinal_trajectory_preserves_g13_review_semantics():
    result = evaluate_authority_composition(_input(cdg="REVIEW"))

    assert result.result == "RESTRICT"
    assert result.result_core["authority_reason"] == "G13_REVIEW"


def test_binding_composition_marks_g13_as_enforced():
    value = _input(cdg="HALT")
    value = replace(value, shadow_mode=False)
    result = evaluate_authority_composition(value)
    assert result.result == "RESTRICT"
    assert result.result_core["authority_reason"] == "G13_HALT"
    assert result.result_core["enforcement"] == "BINDING"


def test_missing_epistemic_input_is_explicit_and_not_permission():
    result = evaluate_authority_composition(_input(cd="REVIEW", cd_applicability="MISSING"))

    assert result.result == "RESTRICT"
    assert result.input_core["applicability"]["CD"] == "MISSING"
    assert result.result_core["authority_reason"] == "LOCAL_EPISTEMIC_DENIAL"


def test_retry_and_replay_have_one_canonical_composition_identity():
    value = _input()
    first = evaluate_authority_composition(value)
    replay = replay_authority_composition(value)
    retry = evaluate_authority_composition(value)

    assert first.policy_evaluation_id == retry.policy_evaluation_id
    assert first.replay_identity == retry.replay_identity
    assert first.input_hash == replay.input_hash
    assert first.result_hash == replay.result_hash


def test_gamma_changes_are_not_composition_inputs():
    first = evaluate_authority_composition(_input())
    changed_gamma = evaluate_authority_composition(_input())

    assert changed_gamma.result == first.result
    assert changed_gamma.input_hash == first.input_hash
