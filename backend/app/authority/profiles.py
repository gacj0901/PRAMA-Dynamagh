"""Versioned grants for trusted service callers; no HTTP or execution integration.

The caller owns authorization and the transaction. This module never commits,
dispatches work, issues permits, or calls a gateway. Lifecycle is append-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.domain.mandates import AgentAuthorityProfile, AgentIdentity, AuthorityProfileEvent, utc_now
from app.pramagraph.evaluation import digest

AUTHORITY_HASH_VERSION = "agent-authority-profile-v0"
Status = Literal["ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("AUTHORITY_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def _terms(values: list[str]) -> list[str]:
    # Trim/deduplicate only. Intent/action names are case-sensitive runtime keys.
    result = sorted({value.strip() for value in values})
    if any(not value or len(value) > 255 for value in result):
        raise ValueError("AUTHORITY_TERM_INVALID")
    return result


class AuthorityProfileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)

    status: Status = "ACTIVE"
    valid_from: datetime
    valid_until: datetime | None = None
    total_budget_usdc: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    per_action_budget_usdc: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    rolling_budget_usdc: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    rolling_window_seconds: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    allowed_intents: list[str] = Field(default_factory=list)
    allowed_action_kinds: list[str] = Field(default_factory=list)
    telegraph_allowed: bool = False
    external_execution_allowed: bool = False
    anchoring_allowed: bool = False
    erc8183_allowed: bool = False
    concurrency_limit: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    cadence_seconds: int | None = Field(default=None, ge=0, le=2147483647, strict=True)
    max_executions_per_window: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    execution_window_seconds: int | None = Field(default=None, gt=0, le=2147483647, strict=True)
    review_required_above_usdc: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=6)
    unlimited_budget: bool = False
    unlimited_execution_rate: bool = False
    policy_version: str = Field(default="agent-authority-v0", min_length=1, max_length=64)

    @field_validator("allowed_intents", "allowed_action_kinds")
    @classmethod
    def normalize_terms(cls, values):
        return _terms(values)

    @field_validator("valid_from", "valid_until")
    @classmethod
    def normalize_time(cls, value):
        return None if value is None else _utc(value)

    @field_validator("policy_version")
    @classmethod
    def normalize_policy(cls, value):
        if not value.strip():
            raise ValueError("AUTHORITY_POLICY_VERSION_REQUIRED")
        return value.strip()

    @model_validator(mode="after")
    def valid_interval(self):
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("AUTHORITY_VALIDITY_INVALID")
        if self.unlimited_budget and any(value is not None for value in (
            self.total_budget_usdc, self.per_action_budget_usdc,
            self.rolling_budget_usdc, self.review_required_above_usdc,
        )):
            raise ValueError("AUTHORITY_UNLIMITED_BUDGET_CONFLICT")
        if self.unlimited_execution_rate and any(value is not None for value in (
            self.cadence_seconds, self.max_executions_per_window,
            self.execution_window_seconds,
        )):
            raise ValueError("AUTHORITY_UNLIMITED_RATE_CONFLICT")
        return self


def _canonical(value):
    if isinstance(value, datetime):
        return _utc(value).isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("AUTHORITY_BUDGET_INVALID")
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def canonical_authority_payload(profile: AgentAuthorityProfile) -> dict:
    """Hash the immutable grant, including its initial status, never its DB id.

    Lifecycle status is a separately auditable overlay; it cannot rewrite this
    hash. Legacy JSON fields are retained as-is, never silently interpreted.
    """
    values = {key: getattr(profile, key) for key in AuthorityProfileSpec.model_fields}
    for key in ("allowed_intents", "allowed_action_kinds"):
        values[key] = _terms(values[key])
    for key in (
        "telegraph_allowed", "external_execution_allowed", "anchoring_allowed",
        "erc8183_allowed", "unlimited_budget", "unlimited_execution_rate",
    ):
        values[key] = bool(values[key])
    values.update(
        hash_version=AUTHORITY_HASH_VERSION,
        agent_identity_id=profile.agent_identity_id,
        principal_id=profile.principal_id,
        version=profile.version,
        legacy_rolling_budget=profile.rolling_budget,
        legacy_cadence_policy=profile.cadence_policy,
        legacy_human_review_thresholds=profile.human_review_thresholds,
    )
    return _canonical(values)


def compute_authority_hash(profile: AgentAuthorityProfile) -> str:
    return digest(canonical_authority_payload(profile))


class AuthorityResolutionError(ValueError):
    """Structured audit context without hidden writes in the read resolver."""

    def __init__(self, code, agent_identity_id, profile_ids=()):
        super().__init__(code)
        self.code = code
        self.agent_identity_id = agent_identity_id
        self.profile_ids = tuple(sorted(profile_ids))


def _actor(created_by: str) -> str:
    if not isinstance(created_by, str) or not created_by.strip() or len(created_by) > 255:
        raise ValueError("AUTHORITY_ACTOR_REQUIRED")
    return created_by.strip()


def list_authority_profiles(session, agent_identity_id: str) -> list[AgentAuthorityProfile]:
    return list(session.scalars(select(AgentAuthorityProfile).where(
        AgentAuthorityProfile.agent_identity_id == agent_identity_id,
    ).order_by(AgentAuthorityProfile.version)))


def effective_profile_status(session, profile, at_time=None):
    at = _utc(at_time or utc_now())
    event = session.scalars(select(AuthorityProfileEvent).where(
        AuthorityProfileEvent.authority_profile_id == profile.id,
        AuthorityProfileEvent.effective_at <= at,
    ).order_by(AuthorityProfileEvent.effective_at.desc(), AuthorityProfileEvent.sequence.desc())).first()
    return event.status if event is not None else profile.status


def get_effective_authority_profile(session, agent_identity_id, at_time=None):
    at = _utc(at_time or utc_now())
    candidates = session.scalars(select(AgentAuthorityProfile).where(
        AgentAuthorityProfile.agent_identity_id == agent_identity_id,
        AgentAuthorityProfile.valid_from <= at,
        (AgentAuthorityProfile.valid_until.is_(None)) | (AgentAuthorityProfile.valid_until > at),
    )).all()
    active = [p for p in candidates if effective_profile_status(session, p, at) == "ACTIVE"]
    if len(active) != 1:
        raise AuthorityResolutionError(
            "AMBIGUOUS_AUTHORITY_PROFILE" if active else "NO_AUTHORITY_PROFILE",
            agent_identity_id, [p.id for p in active],
        )
    profile = active[0]
    if not profile.authority_hash or profile.authority_hash != compute_authority_hash(profile):
        raise AuthorityResolutionError("AUTHORITY_HASH_UNVERIFIED", agent_identity_id, [profile.id])
    return profile


def create_authority_profile(session, agent_identity_id, spec: AuthorityProfileSpec, *, created_by):
    """Trusted caller only. Lock the real agent to allocate the next version."""
    spec = AuthorityProfileSpec.model_validate(spec.model_dump())
    actor = _actor(created_by)
    identity = session.scalar(select(AgentIdentity).where(
        AgentIdentity.agent_id == agent_identity_id,
    ).with_for_update())
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    version = 1 + (session.scalar(select(func.max(AgentAuthorityProfile.version)).where(
        AgentAuthorityProfile.agent_identity_id == agent_identity_id,
    )) or 0)
    profile = AgentAuthorityProfile(
        agent_identity_id=identity.agent_id, version=version, principal_id=None,
        created_by=actor, rolling_budget=None, cadence_policy=None,
        human_review_thresholds={}, **spec.model_dump(),
    )
    profile.authority_hash = compute_authority_hash(profile)
    session.add(profile)
    session.flush()
    return profile


def set_authority_profile_status(session, agent_identity_id, profile_id, status: Status, *, created_by, reason, effective_at=None):
    """Append a suspension/revocation; never modify an existing profile row."""
    actor = _actor(created_by)
    if status not in {"SUSPENDED", "REVOKED", "EXPIRED"}:
        raise ValueError("AUTHORITY_STATUS_TRANSITION_INVALID")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("AUTHORITY_CHANGE_REASON_REQUIRED")
    now = utc_now()
    at = _utc(effective_at) if effective_at else now
    if at < now:
        raise ValueError("AUTHORITY_RETROACTIVE_CHANGE_FORBIDDEN")
    profile = session.scalar(select(AgentAuthorityProfile).where(
        AgentAuthorityProfile.agent_identity_id == agent_identity_id,
        AgentAuthorityProfile.authority_profile_id == profile_id,
    ).with_for_update())
    if profile is None:
        raise ValueError("NO_AUTHORITY_PROFILE")
    if not profile.authority_hash or profile.authority_hash != compute_authority_hash(profile):
        raise ValueError("AUTHORITY_HASH_UNVERIFIED")
    last = session.scalars(select(AuthorityProfileEvent).where(
        AuthorityProfileEvent.authority_profile_id == profile_id,
    ).order_by(AuthorityProfileEvent.sequence.desc())).first()
    previous = last.status if last else profile.status
    if previous in {"REVOKED", "EXPIRED"} or last and at < last.effective_at:
        raise ValueError("AUTHORITY_STATUS_TRANSITION_INVALID")
    event = AuthorityProfileEvent(
        authority_profile_id=profile.id, sequence=last.sequence + 1 if last else 1,
        status=status, effective_at=at, created_by=actor, reason=reason.strip(),
        authority_hash=profile.authority_hash,
    )
    session.add(event)
    session.flush()
    return event


def version_authority_profile(session, agent_identity_id, previous_profile_id, spec, *, created_by, reason):
    """Atomic explicit replacement. Overlaps from independent creates stay ambiguous."""
    # Savepoint prevents partial revocation if creating the replacement fails.
    with session.begin_nested():
        # Same agent lock/order as creation serializes replacement and version allocation.
        identity = session.scalar(select(AgentIdentity).where(
            AgentIdentity.agent_id == agent_identity_id,
        ).with_for_update())
        if identity is None:
            raise ValueError("AGENT_IDENTITY_MISSING")
        spec = AuthorityProfileSpec.model_validate(spec.model_dump())
        now = utc_now()
        if spec.valid_from < now:
            raise ValueError("AUTHORITY_RETROACTIVE_CHANGE_FORBIDDEN")
        set_authority_profile_status(
            session, agent_identity_id, previous_profile_id, "REVOKED",
            created_by=created_by, reason=reason, effective_at=spec.valid_from,
        )
        return create_authority_profile(session, agent_identity_id, spec, created_by=created_by)
