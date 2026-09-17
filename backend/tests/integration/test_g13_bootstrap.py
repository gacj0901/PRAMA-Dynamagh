"""G13-D bounded cold-start authority tests (no network or payment)."""
import inspect
import uuid
from decimal import Decimal
from datetime import timedelta

import pytest

from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy, pre_next_action_gate
from app.authority.bootstrap import (
    BOOTSTRAP_ACTION_KIND,
    BOOTSTRAP_CONSUMED_EVENT,
    BOOTSTRAP_CREATED_EVENT,
    BOOTSTRAP_SCHEMA_VERSION,
    bootstrap_eligibility,
    bootstrap_remaining,
    compute_bootstrap_hash,
    consume_bootstrap_authority,
    create_bootstrap_authority,
    get_bootstrap_authority,
    revoke_bootstrap_authority,
)
from app.authority.composition import AuthorityCompositionInput, evaluate_authority_composition
from app.authority.profiles import AuthorityProfileSpec, create_authority_profile
from app.domain.mandates import AgentIdentity, AutonomyPolicy, UsageEvent, utc_now


def subject(session, prefix="bootstrap"):
    token = uuid.uuid4().hex
    policy = AutonomyPolicy(
        name=f"{prefix}-policy-{token}", enabled=False, version="autonomy-policy-v0",
        mandate_template={"title": "bootstrap", "instruction": "Produce one attributable observation."},
        acquisition_mode="TELEGRAPH_HTTP", allow_telegraph_http=True, allow_erc8183=False,
        allow_anchor=False, strict_verification=True, read_only_replay=False,
        cadence_seconds=900, dedupe_window_seconds=900, max_usdc_per_run=Decimal("0.010000"),
        max_usdc_per_day=Decimal("0.010000"), max_runs_per_day=1, max_concurrent_runs=1,
        state="DRAFT",
    )
    session.add(policy); session.flush()
    identity = AgentIdentity(agent_id=f"{prefix}-agent-{token}", name="bootstrap subject", origin="INTERNAL_AUTONOMY", policy_id=policy.policy_id)
    session.add(identity); session.flush()
    profile = create_authority_profile(
        session, identity.agent_id,
        AuthorityProfileSpec(
            valid_from=utc_now() - timedelta(seconds=1), total_budget_usdc=Decimal("0.010000"),
            per_action_budget_usdc=Decimal("0.010000"), rolling_budget_usdc=Decimal("0.010000"),
            rolling_window_seconds=86400, allowed_action_kinds=[BOOTSTRAP_ACTION_KIND],
            telegraph_allowed=True, external_execution_allowed=True, concurrency_limit=1,
            max_executions_per_window=1, execution_window_seconds=86400,
            review_required_above_usdc=Decimal("0.010000"), policy_version="bootstrap-test-v1",
        ), created_by="pytest",
    )
    return identity, profile, policy


def cold_start_g13(agent_id):
    return evaluate_g13_policy(G13PolicyInput.from_observations(agent_id, []))


def grant(session, identity, profile, policy, **kwargs):
    return create_bootstrap_authority(
        session, agent_identity_id=identity.agent_id,
        authority_profile_id=profile.authority_profile_id, policy_id=policy.policy_id,
        created_by="pytest", **kwargs,
    )


def test_cold_start_without_bootstrap_remains_review(session):
    identity, profile, policy = subject(session)
    g13 = cold_start_g13(identity.agent_id)
    ok, reason, authority = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=g13, action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.010000"))
    assert g13.result == "REVIEW" and g13.triggered_rule_ids == ("G13_REQUIRED_TRAJECTORY_MISSING",)
    assert not ok and reason == "BOOTSTRAP_AUTHORITY_UNAVAILABLE" and authority is None


def test_explicit_bootstrap_makes_only_cold_start_eligible(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    g13 = cold_start_g13(identity.agent_id)
    ok, reason, resolved = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=g13, action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.010000"))
    assert ok and reason == "BOOTSTRAP_AUTHORIZATION" and resolved.bootstrap_authority_id == authority.bootstrap_authority_id
    assert g13.result == "REVIEW" and bootstrap_remaining(authority) == 1


def test_creation_is_explicit_hashed_and_audited(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    assert authority.schema_version == BOOTSTRAP_SCHEMA_VERSION
    assert authority.authority_hash == compute_bootstrap_hash(authority)
    event = session.query(UsageEvent).filter_by(event_type=BOOTSTRAP_CREATED_EVENT).one()
    assert event.metadata_["bootstrap_authority_id"] == authority.bootstrap_authority_id
    assert event.metadata_["remaining_after"] == 1


def test_g13_result_is_never_rewritten(session):
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    g13 = cold_start_g13(identity.agent_id)
    assert g13.result == "REVIEW"


def test_composition_distinguishes_bootstrap_source(session):
    value = AuthorityCompositionInput(
        agent_id="a", run_id="r", action_id="x", action_kind=BOOTSTRAP_ACTION_KIND,
        applicability={"CD": "NOT_APPLICABLE", "G12": "APPLICABLE", "CDG": "APPLICABLE"},
        epistemic_result="PERMIT", epistemic_evaluation_id=None, epistemic_result_hash=None,
        g12_result="PERMIT", g12_input_hash="g12", longitudinal_result="REVIEW",
        longitudinal_evaluation_id="g13", longitudinal_result_hash="g13h",
        throttled_constraints_satisfied=False, current_runtime_action="EXECUTE",
        bootstrap_authorized=True, shadow_mode=False,
    )
    result = evaluate_authority_composition(value)
    assert result.result == "ALLOW"
    assert result.triggered_rule_ids == ("BOOTSTRAP_AUTHORIZATION",)
    assert result.result_core["authorization_source"] == "BOOTSTRAP"
    assert result.input_core["bootstrap_authorized"] is True


def test_g12_denial_blocks_bootstrap(session):
    allowed, reason = pre_next_action_gate(local_decision="PERMIT", economic_authorized=False, longitudinal_result="REVIEW", bootstrap_authorized=True)
    assert not allowed and reason == "G12_ECONOMIC_DENIAL"


def test_scope_is_enforced(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy, allowed_action_kinds=[BOOTSTRAP_ACTION_KIND])
    ok, reason, _ = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=cold_start_g13(identity.agent_id), action_kind="OTHER_ACTION", amount=Decimal("0.001"))
    assert not ok and reason == "AUTHORITY_ACTION_NOT_ALLOWED"
    assert bootstrap_remaining(authority) == 1


def test_budget_ceiling_is_enforced(session):
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    ok, reason, _ = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=cold_start_g13(identity.agent_id), action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.010001"))
    assert not ok and reason == "BOOTSTRAP_BUDGET_EXCEEDED"


def test_halt_cannot_bootstrap(session):
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    g13 = type("Core", (), {"result": "HALT", "triggered_rule_ids": ("G13_IDENTITY_OR_TRAJECTORY_INTEGRITY",)})()
    ok, reason, _ = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=g13, action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    assert not ok and reason == "BOOTSTRAP_NOT_COLD_START"


def test_failure_review_cannot_bootstrap(session):
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    g13 = type("Core", (), {"result": "REVIEW", "triggered_rule_ids": ("G13_REPEATED_EXECUTION_FAILURE",)})()
    ok, reason, _ = bootstrap_eligibility(session, identity=identity, policy=policy, profile=profile, g13_core=g13, action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    assert not ok and reason == "BOOTSTRAP_NOT_COLD_START"


def test_identity_mismatch_cannot_bootstrap(session):
    identity, profile, policy = subject(session)
    _, other_profile, _ = subject(session, "other")
    with pytest.raises(ValueError, match="BOOTSTRAP_PROFILE_IDENTITY_MISMATCH"):
        grant(session, identity, other_profile, policy)


def test_policy_mismatch_cannot_bootstrap(session):
    identity, profile, policy = subject(session)
    other, _, other_policy = subject(session, "other-policy")
    with pytest.raises(ValueError, match="BOOTSTRAP_POLICY_IDENTITY_MISMATCH"):
        grant(session, identity, profile, other_policy)


def test_missing_identity_cannot_bootstrap(session):
    with pytest.raises(ValueError, match="AGENT_IDENTITY_MISSING"):
        create_bootstrap_authority(session, agent_identity_id="missing", authority_profile_id="missing", policy_id="missing", created_by="pytest")


def test_consumption_is_single_use_and_audited(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="action-1", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.010000"), run_id="run-1")
    assert bootstrap_remaining(authority) == 0 and authority.status == "EXHAUSTED"
    event = session.query(UsageEvent).filter_by(event_type=BOOTSTRAP_CONSUMED_EVENT).one()
    assert event.metadata_["authorization_source"] == "BOOTSTRAP"
    with pytest.raises(ValueError, match="BOOTSTRAP_AUTHORITY_EXHAUSTED"):
        consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="action-2", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))


def test_same_action_is_idempotent(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    first = consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="same", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    second = consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="same", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    assert first.bootstrap_authority_id == second.bootstrap_authority_id and bootstrap_remaining(authority) == 0
    assert session.query(UsageEvent).filter_by(event_type=BOOTSTRAP_CONSUMED_EVENT).count() == 1


def test_hash_remains_replayable_after_consumption(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    original = authority.authority_hash
    consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="replay", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    assert authority.authority_hash == original


def test_revocation_is_fail_closed(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    revoke_bootstrap_authority(session, authority.bootstrap_authority_id, created_by="pytest", reason="operator revoke")
    assert authority.status == "REVOKED" and not authority.enabled
    assert get_bootstrap_authority(session, identity.agent_id, policy.policy_id) is None


def test_revoke_requires_reason(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    with pytest.raises(ValueError, match="BOOTSTRAP_AUTHORITY_REASON_REQUIRED"):
        revoke_bootstrap_authority(session, authority.bootstrap_authority_id, created_by="pytest", reason="")


def test_new_subject_has_no_trajectory_or_synthetic_observation(session):
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    g13 = cold_start_g13(identity.agent_id)
    assert not g13.observation_refs and g13.result_core["distinct_failure_count"] == 0


def test_provisioning_activation_still_requires_canonical_binding(session):
    from app.authority.provisioning import validate_policy_activation
    identity, profile, policy = subject(session)
    assert validate_policy_activation(session, policy)[0].agent_id == identity.agent_id
    assert policy.state == "DRAFT" and policy.enabled is False


def test_bootstrap_module_is_access_plane_agnostic():
    source = inspect.getsource(__import__("app.authority.bootstrap", fromlist=["bootstrap_eligibility"]))
    assert "GATEWAY" not in source and "MCP" not in source and "Telegraph" not in source


def test_normal_g13_source_remains_distinct():
    value = AuthorityCompositionInput(
        agent_id="a", run_id="r", action_id="x", action_kind=BOOTSTRAP_ACTION_KIND,
        applicability={"CD": "NOT_APPLICABLE", "G12": "APPLICABLE", "CDG": "APPLICABLE"},
        epistemic_result="PERMIT", epistemic_evaluation_id=None, epistemic_result_hash=None,
        g12_result="PERMIT", g12_input_hash="g12", longitudinal_result="CONTINUE",
        longitudinal_evaluation_id="g13", longitudinal_result_hash="g13h",
        throttled_constraints_satisfied=False, current_runtime_action="EXECUTE",
        shadow_mode=False,
    )
    result = evaluate_authority_composition(value)
    assert result.result == "ALLOW" and result.result_core["authorization_source"] == "NORMAL_G13"


def test_restart_does_not_replenish_allowance(session):
    identity, profile, policy = subject(session)
    authority = grant(session, identity, profile, policy)
    consume_bootstrap_authority(session, grant_id=authority.bootstrap_authority_id, action_id="restart", action_kind=BOOTSTRAP_ACTION_KIND, amount=Decimal("0.001"))
    session.expire_all()
    restored = session.get(type(authority), authority.bootstrap_authority_id)
    assert restored.status == "EXHAUSTED" and bootstrap_remaining(restored) == 0


def test_second_action_requires_normal_g13(session):
    allowed, reason = pre_next_action_gate(local_decision="PERMIT", economic_authorized=True, longitudinal_result="REVIEW", bootstrap_authorized=False)
    assert not allowed and reason == "G13_REVIEW"


def test_provider_names_are_not_authority_inputs():
    source = inspect.getsource(evaluate_authority_composition)
    assert "MCP" not in source and "provider" not in source.lower()


def test_scheduler_can_create_only_the_bounded_cold_start_run(session, monkeypatch):
    from app.autonomy.service import schedule_due
    identity, profile, policy = subject(session)
    grant(session, identity, profile, policy)
    policy.enabled = True
    policy.state = "ACTIVE"
    monkeypatch.setenv("FULL_AUTONOMY_ENABLED", "true")
    monkeypatch.setenv("FULL_AUTONOMY_AGENT_ALLOWLIST", identity.agent_id)
    run = schedule_due(session, policy, global_switch=True)
    assert run is not None and run.agent_identity_id == identity.agent_id
    authority = get_bootstrap_authority(session, identity.agent_id, policy.policy_id)
    assert authority is not None and bootstrap_remaining(authority) == 1
