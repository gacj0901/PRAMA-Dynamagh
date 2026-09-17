"""Canonical autonomous-subject provisioning stays atomic and fail-closed."""

import uuid
from decimal import Decimal

import pytest

from app.authority.profiles import get_effective_authority_profile
from app.authority.provisioning import (
    provision_autonomous_subject,
    validate_policy_activation,
)
from app.domain.mandates import AgentIdentity, AgentAuthorityProfile, AutonomyPolicy


def _kwargs(prefix: str = "subject"):
    token = uuid.uuid4().hex
    return {
        "agent_id": f"{prefix}-agent-{token}",
        "name": f"{prefix} authority subject",
        "policy_name": f"{prefix}-policy-{token}",
        "title": "Canonical provisioning test",
        "instruction": "Produce one attributable observation.",
        "max_payment_usdc": Decimal("0.010000"),
    }


def test_provisioning_binds_identity_profile_policy_in_safe_draft(session):
    result = provision_autonomous_subject(session, **_kwargs())
    assert result.identity.origin == "INTERNAL_AUTONOMY"
    assert result.identity.policy_id == result.policy.policy_id
    assert result.profile.agent_identity_id == result.identity.agent_id
    assert result.policy.enabled is False and result.policy.state == "DRAFT"
    assert get_effective_authority_profile(session, result.identity.agent_id) is result.profile
    assert validate_policy_activation(session, result.policy)[0] is result.identity


def test_provisioning_is_atomic_when_profile_creation_fails(session, monkeypatch):
    import app.authority.provisioning as provisioning

    original = provisioning.create_authority_profile

    def fail(*args, **kwargs):
        raise ValueError("PROFILE_CREATION_FAILED")

    monkeypatch.setattr(provisioning, "create_authority_profile", fail)
    values = _kwargs("atomic")
    with pytest.raises(ValueError, match="PROFILE_CREATION_FAILED"):
        provisioning.provision_autonomous_subject(session, **values)
    session.rollback()
    assert session.query(AgentIdentity).filter_by(agent_id=values["agent_id"]).one_or_none() is None
    assert session.query(AutonomyPolicy).filter_by(name=values["policy_name"]).one_or_none() is None
    monkeypatch.setattr(provisioning, "create_authority_profile", original)


def test_activation_fails_closed_without_canonical_identity(session):
    policy = AutonomyPolicy(
        name="unbound-policy-" + uuid.uuid4().hex,
        enabled=False,
        version="autonomy-policy-v0",
        mandate_template={"title": "unbound", "instruction": "offline"},
        acquisition_mode="TELEGRAPH_HTTP", allow_telegraph_http=True,
        allow_erc8183=False, allow_anchor=False, strict_verification=True,
        read_only_replay=False, cadence_seconds=900, dedupe_window_seconds=900,
        max_usdc_per_run=Decimal("0.010000"), max_usdc_per_day=Decimal("0.010000"),
        max_runs_per_day=1, max_concurrent_runs=1, state="DRAFT",
    )
    session.add(policy)
    session.flush()
    with pytest.raises(ValueError, match="AGENT_IDENTITY_MISSING"):
        validate_policy_activation(session, policy)


def test_two_provisioned_subjects_do_not_cross_contaminate(session):
    first = provision_autonomous_subject(session, **_kwargs("first"))
    second = provision_autonomous_subject(session, **_kwargs("second"))
    assert validate_policy_activation(session, first.policy)[0].agent_id == first.identity.agent_id
    assert validate_policy_activation(session, second.policy)[0].agent_id == second.identity.agent_id
    assert first.profile.agent_identity_id != second.profile.agent_identity_id
    assert session.query(AgentAuthorityProfile).filter_by(agent_identity_id=first.identity.agent_id).count() == 1
    assert session.query(AgentAuthorityProfile).filter_by(agent_identity_id=second.identity.agent_id).count() == 1
