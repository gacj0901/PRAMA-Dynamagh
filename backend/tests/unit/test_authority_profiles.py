from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.authority.profiles import AuthorityProfileSpec, canonical_authority_payload, compute_authority_hash
from app.domain.mandates import AgentAuthorityProfile
from app.main import app


def profile(**changes):
    values = AuthorityProfileSpec(valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc)).model_dump()
    values.update(changes)
    return AgentAuthorityProfile(agent_identity_id="unit-test-agent", version=1,
                                 principal_id=None, rolling_budget=None, cadence_policy=None,
                                 human_review_thresholds={}, **values)


def test_hash_replays_decimal_time_and_set_representations():
    first = profile(total_budget_usdc=Decimal("1.000000"), allowed_intents=["B", "A", "A"])
    second = profile(total_budget_usdc=Decimal("1"), allowed_intents=[" A ", "B"],
                     valid_from=datetime(2025, 12, 31, 18, tzinfo=timezone(timedelta(hours=-6))))
    second.id = "different-database-id"
    second.created_at = datetime.now(timezone.utc)
    second.created_by = "different-audit-actor"
    assert compute_authority_hash(first) == compute_authority_hash(second)
    assert "authority_profile_id" not in canonical_authority_payload(first)


@pytest.mark.parametrize("field,value", [
    ("total_budget_usdc", Decimal("2")), ("per_action_budget_usdc", Decimal("0")),
    ("rolling_budget_usdc", Decimal("2")), ("rolling_window_seconds", 60),
    ("version", 2), ("status", "REVOKED"), ("allowed_intents", ["A"]),
    ("allowed_action_kinds", ["TELEGRAPH_HTTP"]), ("telegraph_allowed", True),
    ("external_execution_allowed", True), ("anchoring_allowed", True),
    ("erc8183_allowed", True), ("concurrency_limit", 2), ("cadence_seconds", 0),
    ("max_executions_per_window", 2), ("execution_window_seconds", 60),
    ("review_required_above_usdc", Decimal("1")), ("policy_version", "other"),
    ("agent_identity_id", "another-unit-test-agent"),
])
def test_every_authority_mutation_changes_hash(field, value):
    original, changed = profile(), profile()
    setattr(changed, field, value)
    assert compute_authority_hash(original) != compute_authority_hash(changed)


@pytest.mark.parametrize("changes", [
    {"total_budget_usdc": "-0.1"}, {"per_action_budget_usdc": "-1"},
    {"rolling_budget_usdc": "-1"}, {"review_required_above_usdc": "-1"},
    {"total_budget_usdc": "NaN"}, {"total_budget_usdc": "0.0000001"},
    {"concurrency_limit": 0}, {"concurrency_limit": -1}, {"concurrency_limit": True},
    {"cadence_seconds": -1}, {"rolling_window_seconds": 0},
    {"execution_window_seconds": 0}, {"max_executions_per_window": 0},
    {"allowed_intents": [" "]}, {"allowed_action_kinds": [""]},
    {"status": "UNKNOWN"}, {"policy_version": " "},
    {"valid_until": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    {"valid_from": datetime(2026, 1, 1)}, {"principal_id": "self-asserted"},
])
def test_invalid_spec_rejected_before_persistence(changes):
    with pytest.raises(ValidationError):
        AuthorityProfileSpec(**{"valid_from": datetime(2026, 1, 1, tzinfo=timezone.utc), **changes})


def test_normalization_preserves_case_sensitive_keys_and_zero_budget():
    spec = AuthorityProfileSpec(valid_from=datetime.now(timezone.utc), total_budget_usdc=0,
                                cadence_seconds=0, allowed_intents=[" X ", "X", "x"])
    assert spec.allowed_intents == ["X", "x"]
    assert spec.total_budget_usdc == 0


def test_m2m_has_no_authority_write_route(monkeypatch):
    monkeypatch.setenv("PRAMA_M2M_API_TOKEN", "unit-test-only")
    response = TestClient(app).post("/v1/authority/profiles", json={},
                                    headers={"Authorization": "Bearer unit-test-only"})
    assert response.status_code == 405
    assert "post" not in app.openapi()["paths"]["/v1/authority/profiles"]
