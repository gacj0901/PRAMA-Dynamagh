"""Canonical provisioning for an attributable autonomous execution subject.

Provisioning is deliberately a single transaction owned by the caller.  It
creates the identity, its versioned authority profile, and a safe DRAFT policy
bound through ``AgentIdentity.policy_id``.  It never activates a policy or
dispatches work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.identity import TRAJECTORY_VERSION
from app.authority.profiles import (
    AuthorityProfileSpec,
    create_authority_profile,
    get_effective_authority_profile,
)
from app.autonomy.service import validate_policy
from app.domain.mandates import (
    AgentIdentity,
    AgentIdentityOrigin,
    AgentIdentityStatus,
    AutonomyPolicy,
    utc_now,
)

PROVISIONING_VERSION = "autonomous-subject-provisioning-v1"
DEFAULT_MAX_PAYMENT = Decimal("0.010000")
DEFAULT_CADENCE_SECONDS = 900


@dataclass(frozen=True)
class ProvisionedSubject:
    identity: AgentIdentity
    profile: Any
    policy: AutonomyPolicy


def _required_text(value: str, code: str, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(code)
    return value.strip()


def provision_autonomous_subject(
    session: Session,
    *,
    agent_id: str,
    name: str,
    policy_name: str,
    title: str,
    instruction: str,
    max_payment_usdc: Decimal = DEFAULT_MAX_PAYMENT,
    cadence_seconds: int = DEFAULT_CADENCE_SECONDS,
    created_by: str = "operator",
    principal_id: str | None = None,
) -> ProvisionedSubject:
    """Atomically create one autonomous subject in a safe, inactive state.

    The function intentionally does not commit.  A caller can compose it with
    other administrative work and commit exactly once, or roll back the whole
    subject on any error.
    """
    agent_id = _required_text(agent_id, "AGENT_ID_REQUIRED")
    name = _required_text(name, "AGENT_NAME_REQUIRED")
    policy_name = _required_text(policy_name, "AUTONOMY_POLICY_NAME_REQUIRED")
    title = _required_text(title, "AUTONOMY_POLICY_TITLE_REQUIRED")
    instruction = _required_text(instruction, "AUTONOMY_POLICY_INSTRUCTION_REQUIRED", 20_000)
    created_by = _required_text(created_by, "AUTHORITY_ACTOR_REQUIRED")
    if principal_id is not None:
        principal_id = _required_text(principal_id, "AUTHORITY_ACTOR_REQUIRED")
    try:
        budget = Decimal(max_payment_usdc)
    except Exception as error:
        raise ValueError("AUTONOMY_PROVISIONING_BUDGET_INVALID") from error
    if not budget.is_finite() or budget <= 0 or budget > DEFAULT_MAX_PAYMENT:
        raise ValueError("AUTONOMY_PROVISIONING_BUDGET_INVALID")
    if isinstance(cadence_seconds, bool) or int(cadence_seconds) < DEFAULT_CADENCE_SECONDS:
        raise ValueError("AUTONOMY_PROVISIONING_CADENCE_INVALID")
    cadence_seconds = int(cadence_seconds)

    if session.get(AgentIdentity, agent_id) is not None:
        raise ValueError("AGENT_IDENTITY_EXISTS")
    if session.scalar(select(AutonomyPolicy).where(AutonomyPolicy.name == policy_name)) is not None:
        raise ValueError("AUTONOMY_POLICY_EXISTS")

    policy_values = {
        "name": policy_name,
        "enabled": False,
        "version": PROVISIONING_VERSION,
        "mandate_template": {"title": title, "instruction": instruction},
        "acquisition_mode": "TELEGRAPH_HTTP",
        "allow_telegraph_http": True,
        "allow_erc8183": False,
        "allow_anchor": False,
        "strict_verification": True,
        "read_only_replay": False,
        "cadence_seconds": cadence_seconds,
        "dedupe_window_seconds": cadence_seconds,
        "max_usdc_per_run": budget,
        "max_usdc_per_day": budget,
        "max_runs_per_day": 1,
        "max_concurrent_runs": 1,
        "state": "DRAFT",
    }
    validate_policy(policy_values)
    policy = AutonomyPolicy(**policy_values)
    session.add(policy)
    session.flush()

    identity = AgentIdentity(
        agent_id=agent_id,
        name=name,
        origin=AgentIdentityOrigin.INTERNAL_AUTONOMY.value,
        status=AgentIdentityStatus.ACTIVE.value,
        trajectory_version=TRAJECTORY_VERSION,
        policy_id=policy.policy_id,
        autonomy_state="ACTIVE",
    )
    session.add(identity)
    session.flush()

    valid_from = utc_now() - timedelta(seconds=1)
    profile_spec = AuthorityProfileSpec(
        valid_from=valid_from,
        total_budget_usdc=budget,
        per_action_budget_usdc=budget,
        rolling_budget_usdc=budget,
        rolling_window_seconds=86_400,
        allowed_intents=[],
        allowed_action_kinds=["TELEGRAPH_HTTP_ACQUISITION"],
        telegraph_allowed=True,
        external_execution_allowed=True,
        concurrency_limit=1,
        max_executions_per_window=1,
        execution_window_seconds=86_400,
        review_required_above_usdc=budget,
        policy_version=PROVISIONING_VERSION,
    )
    profile = create_authority_profile(
        session,
        identity.agent_id,
        profile_spec,
        created_by=created_by,
        principal_id=principal_id,
    )
    return ProvisionedSubject(identity=identity, profile=profile, policy=policy)


def validate_policy_activation(session: Session, policy: AutonomyPolicy):
    """Validate the complete subject before an autonomous policy is enabled."""
    identities = list(session.scalars(select(AgentIdentity).where(
        AgentIdentity.policy_id == policy.policy_id,
    )))
    if not identities:
        raise ValueError("AGENT_IDENTITY_MISSING")
    if len(identities) != 1:
        raise ValueError("AGENT_IDENTITY_AMBIGUOUS")
    identity = identities[0]
    if identity.status != AgentIdentityStatus.ACTIVE.value:
        raise ValueError("AGENT_IDENTITY_INACTIVE")
    try:
        profile = get_effective_authority_profile(session, identity.agent_id)
    except ValueError as error:
        raise ValueError(str(error)) from error
    if profile.agent_identity_id != identity.agent_id:
        raise ValueError("AUTHORITY_IDENTITY_MISMATCH")
    if not profile.external_execution_allowed:
        raise ValueError("AUTHORITY_ACTION_NOT_ALLOWED")
    if policy.acquisition_mode == "TELEGRAPH_HTTP" and not profile.telegraph_allowed:
        raise ValueError("AUTHORITY_ACTION_NOT_ALLOWED")
    if not profile.unlimited_budget:
        if profile.economic_budget is None or profile.per_action_budget is None:
            raise ValueError("AUTHORITY_BUDGET_INVALID")
        if Decimal(profile.per_action_budget) > Decimal(policy.max_usdc_per_run):
            raise ValueError("AUTHORITY_BUDGET_INVALID")
    return identity, profile
