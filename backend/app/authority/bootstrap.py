"""Bounded cold-start authority, independent from access mechanisms."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.authority.profiles import compute_authority_hash
from app.domain.mandates import (
    AgentAuthorityProfile,
    AgentIdentity,
    AutonomyPolicy,
    AutonomyRun,
    BootstrapAuthority,
    UsageEvent,
    utc_now,
)
from app.pramagraph.evaluation import digest

BOOTSTRAP_SCHEMA_VERSION = "g13-cold-start-bootstrap-authority-v1"
BOOTSTRAP_CREATED_EVENT = "BOOTSTRAP_AUTHORITY_CREATED"
BOOTSTRAP_CONSUMED_EVENT = "BOOTSTRAP_AUTHORITY_CONSUMED"
BOOTSTRAP_REVOKED_EVENT = "BOOTSTRAP_AUTHORITY_REVOKED"
BOOTSTRAP_ACTION_KIND = "TELEGRAPH_HTTP_ACQUISITION"
MAX_BOOTSTRAP_ACTIONS = 1
MAX_BOOTSTRAP_SPEND_USDC = Decimal("0.010000")


def _actor(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 255:
        raise ValueError("BOOTSTRAP_AUTHORITY_ACTOR_REQUIRED")
    return value.strip()


def _canonical(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("BOOTSTRAP_AUTHORITY_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("BOOTSTRAP_AUTHORITY_BUDGET_INVALID")
        return format(value.normalize(), "f") if value else "0"
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def canonical_bootstrap_payload(grant: BootstrapAuthority) -> dict:
    return _canonical({
        "schema_version": grant.schema_version,
        "agent_identity_id": grant.agent_identity_id,
        "authority_profile_id": grant.authority_profile_id,
        "policy_id": grant.policy_id,
        "max_actions": grant.max_actions,
        "max_spend_usdc": grant.max_spend_usdc,
        "allowed_action_kinds": sorted(grant.allowed_action_kinds or []),
        "valid_from": grant.valid_from,
        "valid_until": grant.valid_until,
        "created_by": grant.created_by,
    })


def compute_bootstrap_hash(grant: BootstrapAuthority) -> str:
    return digest(canonical_bootstrap_payload(grant))


def _event(session, grant: BootstrapAuthority, event_type: str, metadata: dict) -> None:
    session.add(UsageEvent(
        event_type=event_type,
        metadata_={
            "append_only": True,
            "schema_version": grant.schema_version,
            "bootstrap_authority_id": grant.bootstrap_authority_id,
            "agent_id": grant.agent_identity_id,
            "authority_profile_id": grant.authority_profile_id,
            "policy_id": grant.policy_id,
            "authority_hash": grant.authority_hash,
            **metadata,
        },
    ))
    session.flush()


def create_bootstrap_authority(
    session,
    *,
    agent_identity_id: str,
    authority_profile_id: str,
    policy_id: str,
    created_by: str,
    max_actions: int = MAX_BOOTSTRAP_ACTIONS,
    max_spend_usdc: Decimal = MAX_BOOTSTRAP_SPEND_USDC,
    allowed_action_kinds: list[str] | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> BootstrapAuthority:
    """Create one explicit grant; caller owns the transaction and commit."""
    actor = _actor(created_by)
    if isinstance(max_actions, bool) or int(max_actions) < 1:
        raise ValueError("BOOTSTRAP_AUTHORITY_ACTION_LIMIT_INVALID")
    max_actions = int(max_actions)
    amount = Decimal(max_spend_usdc)
    if not amount.is_finite() or amount <= 0 or amount > MAX_BOOTSTRAP_SPEND_USDC:
        raise ValueError("BOOTSTRAP_AUTHORITY_BUDGET_INVALID")
    identity = session.scalar(select(AgentIdentity).where(
        AgentIdentity.agent_id == agent_identity_id,
    ).with_for_update())
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    if identity.status != "ACTIVE":
        raise ValueError("AGENT_IDENTITY_INACTIVE")
    policy = session.get(AutonomyPolicy, policy_id)
    if policy is None or policy.policy_id != identity.policy_id:
        raise ValueError("BOOTSTRAP_POLICY_IDENTITY_MISMATCH")
    profile = session.scalar(select(AgentAuthorityProfile).where(
        AgentAuthorityProfile.authority_profile_id == authority_profile_id,
        AgentAuthorityProfile.agent_identity_id == agent_identity_id,
    ))
    if profile is None:
        raise ValueError("BOOTSTRAP_PROFILE_IDENTITY_MISMATCH")
    if not profile.authority_hash or profile.authority_hash != compute_authority_hash(profile):
        raise ValueError("AUTHORITY_HASH_UNVERIFIED")
    actions = sorted(set(allowed_action_kinds or [BOOTSTRAP_ACTION_KIND]))
    if not actions or any(not isinstance(item, str) or not item.strip() for item in actions):
        raise ValueError("BOOTSTRAP_AUTHORITY_SCOPE_INVALID")
    start = valid_from or utc_now()
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("BOOTSTRAP_AUTHORITY_TIMEZONE_REQUIRED")
    if valid_until is not None:
        if valid_until.tzinfo is None or valid_until.utcoffset() is None:
            raise ValueError("BOOTSTRAP_AUTHORITY_TIMEZONE_REQUIRED")
        if valid_until <= start:
            raise ValueError("BOOTSTRAP_AUTHORITY_VALIDITY_INVALID")
    existing = session.scalar(select(BootstrapAuthority).where(
        BootstrapAuthority.agent_identity_id == agent_identity_id,
        BootstrapAuthority.policy_id == policy_id,
        BootstrapAuthority.status == "ACTIVE",
    ).with_for_update())
    if existing is not None:
        raise ValueError("BOOTSTRAP_AUTHORITY_EXISTS")
    grant = BootstrapAuthority(
        agent_identity_id=agent_identity_id,
        authority_profile_id=authority_profile_id,
        policy_id=policy_id,
        enabled=True,
        status="ACTIVE",
        max_actions=max_actions,
        consumed_actions=0,
        max_spend_usdc=amount,
        allowed_action_kinds=actions,
        valid_from=start.astimezone(timezone.utc),
        valid_until=valid_until.astimezone(timezone.utc) if valid_until else None,
        created_by=actor,
        schema_version=BOOTSTRAP_SCHEMA_VERSION,
        authority_hash="pending",
    )
    grant.authority_hash = compute_bootstrap_hash(grant)
    session.add(grant)
    session.flush()
    _event(session, grant, BOOTSTRAP_CREATED_EVENT, {
        "max_actions": grant.max_actions,
        "max_spend_usdc": str(grant.max_spend_usdc),
        "allowed_action_kinds": list(grant.allowed_action_kinds),
        "remaining_before": grant.max_actions,
        "remaining_after": grant.max_actions,
    })
    return grant


def get_bootstrap_authority(session, agent_identity_id: str, policy_id: str, *, at: datetime | None = None) -> BootstrapAuthority | None:
    instant = (at or utc_now()).astimezone(timezone.utc)
    grants = list(session.scalars(select(BootstrapAuthority).where(
        BootstrapAuthority.agent_identity_id == agent_identity_id,
        BootstrapAuthority.policy_id == policy_id,
        BootstrapAuthority.enabled.is_(True),
        BootstrapAuthority.status == "ACTIVE",
        BootstrapAuthority.valid_from <= instant,
        (BootstrapAuthority.valid_until.is_(None)) | (BootstrapAuthority.valid_until > instant),
    ).order_by(BootstrapAuthority.created_at.desc(), BootstrapAuthority.bootstrap_authority_id.desc())))
    if len(grants) > 1:
        raise ValueError("BOOTSTRAP_AUTHORITY_AMBIGUOUS")
    if not grants:
        return None
    grant = grants[0]
    if grant.authority_hash != compute_bootstrap_hash(grant):
        raise ValueError("BOOTSTRAP_AUTHORITY_HASH_UNVERIFIED")
    return grant


def bootstrap_remaining(grant: BootstrapAuthority) -> int:
    return max(0, int(grant.max_actions) - int(grant.consumed_actions))


def bootstrap_eligibility(
    session,
    *,
    identity: AgentIdentity,
    policy: AutonomyPolicy,
    profile: AgentAuthorityProfile,
    g13_core,
    action_kind: str,
    amount: Decimal,
) -> tuple[bool, str, BootstrapAuthority | None]:
    """Check cold-start eligibility without consuming the allowance."""
    if identity is None or identity.status != "ACTIVE":
        return False, "AGENT_IDENTITY_INELIGIBLE", None
    if profile is None or profile.agent_identity_id != identity.agent_id:
        return False, "BOOTSTRAP_PROFILE_IDENTITY_MISMATCH", None
    if policy is None or policy.policy_id != identity.policy_id:
        return False, "BOOTSTRAP_POLICY_IDENTITY_MISMATCH", None
    if g13_core is None or g13_core.result != "REVIEW" or tuple(g13_core.triggered_rule_ids) != ("G13_REQUIRED_TRAJECTORY_MISSING",):
        return False, "BOOTSTRAP_NOT_COLD_START", None
    run_count = session.scalar(select(func.count()).select_from(AutonomyRun).where(
        AutonomyRun.agent_identity_id == identity.agent_id,
        AutonomyRun.state != "SKIPPED",
    )) or 0
    if int(run_count) != 0:
        return False, "BOOTSTRAP_TRAJECTORY_EXISTS", None
    if not profile.external_execution_allowed or action_kind not in (profile.allowed_action_kinds or []):
        return False, "AUTHORITY_ACTION_NOT_ALLOWED", None
    if action_kind == BOOTSTRAP_ACTION_KIND and not profile.telegraph_allowed:
        return False, "AUTHORITY_ACTION_NOT_ALLOWED", None
    grant = get_bootstrap_authority(session, identity.agent_id, policy.policy_id)
    if grant is None or bootstrap_remaining(grant) <= 0:
        return False, "BOOTSTRAP_AUTHORITY_UNAVAILABLE", None
    if action_kind not in (grant.allowed_action_kinds or []):
        return False, "BOOTSTRAP_SCOPE_DENIED", grant
    if Decimal(amount) > Decimal(grant.max_spend_usdc):
        return False, "BOOTSTRAP_BUDGET_EXCEEDED", grant
    return True, "BOOTSTRAP_AUTHORIZATION", grant


def consume_bootstrap_authority(
    session,
    *,
    grant_id: str,
    action_id: str,
    action_kind: str,
    amount: Decimal,
    mandate_id: str | None = None,
    run_id: str | None = None,
) -> BootstrapAuthority:
    """Atomically consume one allowance at the external-action commitment."""
    grant = session.scalar(select(BootstrapAuthority).where(
        BootstrapAuthority.bootstrap_authority_id == grant_id,
    ).with_for_update())
    if grant is None:
        raise ValueError("BOOTSTRAP_AUTHORITY_MISSING")
    if grant.authority_hash != compute_bootstrap_hash(grant):
        raise ValueError("BOOTSTRAP_AUTHORITY_HASH_UNVERIFIED")
    prior = [event for event in session.scalars(select(UsageEvent).where(
        UsageEvent.event_type == BOOTSTRAP_CONSUMED_EVENT,
    )) if (event.metadata_ or {}).get("bootstrap_authority_id") == grant_id and (event.metadata_ or {}).get("action_id") == action_id]
    if prior:
        return grant
    if not grant.enabled or grant.status != "ACTIVE" or bootstrap_remaining(grant) <= 0:
        raise ValueError("BOOTSTRAP_AUTHORITY_EXHAUSTED")
    if action_kind not in (grant.allowed_action_kinds or []):
        raise ValueError("BOOTSTRAP_SCOPE_DENIED")
    normalized = Decimal(amount)
    if normalized < 0 or normalized > Decimal(grant.max_spend_usdc):
        raise ValueError("BOOTSTRAP_AUTHORITY_BUDGET_INVALID")
    before = bootstrap_remaining(grant)
    grant.consumed_actions += 1
    if bootstrap_remaining(grant) == 0:
        grant.status = "EXHAUSTED"
    grant.last_consumed_at = utc_now()
    grant.updated_at = grant.last_consumed_at
    session.flush()
    _event(session, grant, BOOTSTRAP_CONSUMED_EVENT, {
        "action_id": action_id,
        "action_kind": action_kind,
        "mandate_id": mandate_id,
        "autonomy_run_id": run_id,
        "amount_usdc": str(normalized),
        "remaining_before": before,
        "remaining_after": bootstrap_remaining(grant),
        "authorization_source": "BOOTSTRAP",
    })
    return grant


def revoke_bootstrap_authority(session, grant_id: str, *, created_by: str, reason: str) -> BootstrapAuthority:
    actor = _actor(created_by)
    grant = session.scalar(select(BootstrapAuthority).where(
        BootstrapAuthority.bootstrap_authority_id == grant_id,
    ).with_for_update())
    if grant is None:
        raise ValueError("BOOTSTRAP_AUTHORITY_MISSING")
    if not reason or not reason.strip():
        raise ValueError("BOOTSTRAP_AUTHORITY_REASON_REQUIRED")
    if grant.status == "ACTIVE":
        grant.status = "REVOKED"
        grant.enabled = False
        grant.updated_at = utc_now()
        _event(session, grant, BOOTSTRAP_REVOKED_EVENT, {"created_by": actor, "reason": reason.strip()})
    return grant


__all__ = [
    "BOOTSTRAP_ACTION_KIND", "BOOTSTRAP_CONSUMED_EVENT", "BOOTSTRAP_CREATED_EVENT",
    "BOOTSTRAP_SCHEMA_VERSION", "MAX_BOOTSTRAP_ACTIONS", "MAX_BOOTSTRAP_SPEND_USDC",
    "bootstrap_eligibility", "bootstrap_remaining", "canonical_bootstrap_payload",
    "compute_bootstrap_hash", "consume_bootstrap_authority", "create_bootstrap_authority",
    "get_bootstrap_authority", "revoke_bootstrap_authority",
]
