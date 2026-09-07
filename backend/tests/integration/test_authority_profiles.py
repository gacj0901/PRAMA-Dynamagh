"""Real PostgreSQL, synthetic identities, zero acquisition/payment traffic."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.authority.profiles import (
    AuthorityProfileSpec, AuthorityResolutionError, canonical_authority_payload,
    compute_authority_hash, create_authority_profile, effective_profile_status,
    get_effective_authority_profile, list_authority_profiles,
    set_authority_profile_status, version_authority_profile,
)
from app.domain.mandates import AgentIdentity, AgentAuthorityProfile, utc_now


@pytest.fixture(autouse=True)
def no_external_traffic(monkeypatch):
    import urllib.request
    from app.workers import acquisition, tasks
    blocked = Mock(side_effect=AssertionError("External traffic forbidden in authority tests"))
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(acquisition, "urlopen", blocked)
    monkeypatch.setattr(tasks, "urlopen", blocked)
    yield
    blocked.assert_not_called()


@pytest.fixture
def agent(session):
    row = AgentIdentity(agent_id=str(uuid.uuid4()), name="synthetic authority test", origin="OTHER")
    session.add(row)
    session.flush()
    return row


def spec(*, reference_time=None, valid_from=None, **changes):
    if valid_from is None:
        valid_from = (reference_time or utc_now()) - timedelta(seconds=10)
    return AuthorityProfileSpec(valid_from=valid_from, **changes)


def create(session, agent, **changes):
    return create_authority_profile(session, agent.agent_id, spec(**changes), created_by="pytest")


def test_valid_profile_binding_and_resolution(session, agent):
    row = create(session, agent, total_budget_usdc=Decimal("0"))
    assert row.id == row.authority_profile_id
    assert row.version == 1 and row.principal_id is None
    assert row.total_budget_usdc == row.economic_budget == 0
    assert row.agent_identity is agent and agent.authority_profiles == [row]
    assert get_effective_authority_profile(session, agent.agent_id) is row
    assert row.authority_hash == compute_authority_hash(row)


def test_versioning_preserves_grant_and_historical_resolution(session, agent):
    first = create(session, agent, total_budget_usdc=1)
    original, original_hash = canonical_authority_payload(first), first.authority_hash
    cutover = utc_now() + timedelta(seconds=30)
    replacement = AuthorityProfileSpec(valid_from=cutover, total_budget_usdc=2)
    second = version_authority_profile(session, agent.agent_id, first.id, replacement,
                                       created_by="pytest", reason="revised budget")
    assert [p.version for p in list_authority_profiles(session, agent.agent_id)] == [1, 2]
    session.expire_all()
    assert canonical_authority_payload(first) == original and first.authority_hash == original_hash
    assert get_effective_authority_profile(session, agent.agent_id, cutover - timedelta(microseconds=1)).id == first.id
    assert get_effective_authority_profile(session, agent.agent_id, cutover).id == second.id


@pytest.mark.parametrize("status", ["SUSPENDED", "REVOKED", "EXPIRED"])
def test_non_active_initial_status_grants_nothing(session, agent, status):
    create(session, agent, status=status)
    with pytest.raises(AuthorityResolutionError, match="NO_AUTHORITY_PROFILE"):
        get_effective_authority_profile(session, agent.agent_id)


@pytest.mark.parametrize("status", ["SUSPENDED", "REVOKED", "EXPIRED"])
def test_lifecycle_is_append_only_and_temporally_resolved(session, agent, status):
    reference_time = utc_now()
    row = create(session, agent, reference_time=reference_time)
    prior = reference_time
    effective_at = reference_time + timedelta(seconds=1)
    event = set_authority_profile_status(session, agent.agent_id, row.id, status,
                                         created_by="pytest", reason="test lifecycle", effective_at=effective_at)
    assert row.status == "ACTIVE" and event.authority_hash == row.authority_hash
    assert get_effective_authority_profile(session, agent.agent_id, prior) is row
    assert effective_profile_status(session, row, effective_at) == status
    with pytest.raises(AuthorityResolutionError, match="NO_AUTHORITY_PROFILE"):
        get_effective_authority_profile(session, agent.agent_id, effective_at)


def test_expired_and_future_profiles_not_effective(session, agent):
    now = utc_now()
    create_authority_profile(session, agent.agent_id,
        AuthorityProfileSpec(valid_from=now - timedelta(days=2), valid_until=now - timedelta(days=1)), created_by="pytest")
    create_authority_profile(session, agent.agent_id,
        AuthorityProfileSpec(valid_from=now + timedelta(days=1)), created_by="pytest")
    with pytest.raises(AuthorityResolutionError, match="NO_AUTHORITY_PROFILE"):
        get_effective_authority_profile(session, agent.agent_id, now)


def test_overlapping_profiles_fail_closed_with_auditable_ids(session, agent):
    first, second = create(session, agent), create(session, agent)
    with pytest.raises(AuthorityResolutionError, match="AMBIGUOUS_AUTHORITY_PROFILE") as error:
        get_effective_authority_profile(session, agent.agent_id)
    assert error.value.agent_identity_id == agent.agent_id
    assert set(error.value.profile_ids) == {first.id, second.id}


def test_cross_agent_isolation(session, agent):
    row = create(session, agent)
    other = AgentIdentity(agent_id=str(uuid.uuid4()), name="other synthetic agent", origin="OTHER")
    session.add(other)
    session.flush()
    with pytest.raises(AuthorityResolutionError, match="NO_AUTHORITY_PROFILE"):
        get_effective_authority_profile(session, other.agent_id)
    with pytest.raises(ValueError, match="NO_AUTHORITY_PROFILE"):
        set_authority_profile_status(session, other.agent_id, row.id, "REVOKED", created_by="pytest", reason="denied")
    assert get_effective_authority_profile(session, agent.agent_id) is row


def test_duplicate_version_rejected_by_postgres(session, agent):
    row = create(session, agent)
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(text("""INSERT INTO agent_authority_profiles
          SELECT (jsonb_populate_record(NULL::agent_authority_profiles,
            to_jsonb(p) || jsonb_build_object('authority_profile_id', CAST(:new_id AS text)))).*
          FROM agent_authority_profiles p WHERE authority_profile_id=:old_id"""),
          {"new_id": str(uuid.uuid4()), "old_id": row.id})


@pytest.mark.parametrize("table,id_column", [
    ("agent_authority_profiles", "authority_profile_id"), ("authority_profile_events", "event_id"),
])
def test_database_preserves_history_against_update_and_delete(session, agent, table, id_column):
    row = create(session, agent)
    event = set_authority_profile_status(session, agent.agent_id, row.id, "SUSPENDED", created_by="pytest", reason="audit")
    key = row.id if table == "agent_authority_profiles" else event.event_id
    for sql in (f"UPDATE {table} SET status='REVOKED' WHERE {id_column}=:key",
                f"DELETE FROM {table} WHERE {id_column}=:key"):
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(text(sql), {"key": key})


def test_reload_preserves_resolution_and_hash(session, agent):
    row = create(session, agent)
    row_id, agent_id, authority_hash = row.id, agent.agent_id, row.authority_hash
    with Session(bind=session.connection(), join_transaction_mode="create_savepoint") as reloaded:
        result = get_effective_authority_profile(reloaded, agent_id)
        assert result.id == row_id and result.authority_hash == authority_hash
        assert compute_authority_hash(result) == authority_hash


def test_unverified_legacy_hash_cannot_grant_v0_authority(session, agent):
    legacy = AgentAuthorityProfile(agent_identity_id=agent.agent_id, version=1)
    session.add(legacy)
    session.flush()
    with pytest.raises(AuthorityResolutionError, match="AUTHORITY_HASH_UNVERIFIED"):
        get_effective_authority_profile(session, agent.agent_id)


def test_revoked_grant_cannot_be_resumed_or_rewritten(session, agent):
    row = create(session, agent)
    set_authority_profile_status(session, agent.agent_id, row.id, "REVOKED", created_by="pytest", reason="final")
    for status in ("ACTIVE", "SUSPENDED"):
        with pytest.raises(ValueError, match="AUTHORITY_STATUS_TRANSITION_INVALID"):
            set_authority_profile_status(session, agent.agent_id, row.id, status, created_by="pytest", reason="denied")


def test_invalid_spec_cannot_be_smuggled_past_service_validation(session, agent):
    invalid = spec().model_copy(update={"total_budget_usdc": Decimal("-1")})
    with pytest.raises(ValueError):
        create_authority_profile(session, agent.agent_id, invalid, created_by="pytest")
    assert list_authority_profiles(session, agent.agent_id) == []
