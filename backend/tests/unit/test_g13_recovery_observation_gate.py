"""Unit tests for the observation-starvation bypass in G13 gates.

Covers the pure-policy surface: `sole_blocker` metadata in
`evaluate_g13_policy` and the `recovery_observation_permitted` branch of
`pre_next_action_gate`. No DB, no runtime — deterministic.
"""

from app.authority.autonomy import pre_next_action_gate


def test_gate_review_blocks_without_probe_or_observation():
    allowed, reason = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="REVIEW",
        recovery_probe_authorized=False,
        recovery_observation_permitted=False,
    )
    assert allowed is False
    assert reason == "G13_REVIEW"


def test_gate_review_allow_via_probe():
    allowed, reason = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="REVIEW",
        recovery_probe_authorized=True,
        recovery_observation_permitted=False,
    )
    assert allowed is True
    assert reason == "NEXT_ACTION_AUTHORIZED"


def test_gate_review_allow_via_recovery_observation():
    """The bypass: sole observation-starvation REVIEW with an unconsumed
    observation permits exactly one run; no other REVIEW cause qualifies."""
    allowed, reason = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="REVIEW",
        recovery_probe_authorized=False,
        recovery_observation_permitted=True,
    )
    assert allowed is True
    assert reason == "NEXT_ACTION_AUTHORIZED"


def test_gate_observation_flag_does_not_override_halt():
    """Invariant: no positive gate overrides an applicable restrictive one.
    The observation flag is scoped to REVIEW only."""
    allowed, reason = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="HALT",
        recovery_probe_authorized=False,
        recovery_observation_permitted=True,
    )
    assert allowed is False
    assert reason == "G13_HALT"


def test_gate_observation_flag_does_not_override_local_denial():
    allowed, reason = pre_next_action_gate(
        local_decision="BLOCK",
        economic_authorized=True,
        longitudinal_result="REVIEW",
        recovery_probe_authorized=False,
        recovery_observation_permitted=True,
    )
    assert allowed is False
    assert reason == "LOCAL_EPISTEMIC_DENIAL"


def test_gate_observation_flag_does_not_override_g12_denial():
    allowed, reason = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=False,
        longitudinal_result="REVIEW",
        recovery_probe_authorized=False,
        recovery_observation_permitted=True,
    )
    assert allowed is False
    assert reason == "G12_ECONOMIC_DENIAL"


def test_gate_default_callers_unchanged():
    """Existing callers that never heard of the bypass get the old behavior:
    omitting the flag means REVIEW blocks, HALT blocks, THROTTLE follows the
    constraints flag, CONTINUE allows."""
    allowed, _ = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="REVIEW",
    )
    assert allowed is False

    allowed, _ = pre_next_action_gate(
        local_decision="PERMIT",
        economic_authorized=True,
        longitudinal_result="THROTTLE",
        throttled_constraints_satisfied=True,
    )
    assert allowed is True
