from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.authority.binding import (
    G13_POLICY_BINDING_MISSING,
    activate_g13_policy_binding,
    current_g13_policy_binding,
    policy_binding_missing_evaluation,
)
from app.authority import runtime
from app.authority.autonomy import G13PolicyInput, evaluate_g13_policy
from app.policy_gate.substrate import replay_policy


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        self.rows = [row for row in self.rows if all(getattr(row, key) == value for key, value in kwargs.items())]
        return self

    def with_for_update(self, **kwargs):
        return self

    def one_or_none(self):
        if len(self.rows) > 1:
            raise AssertionError("expected one binding")
        return self.rows[0] if self.rows else None


class _Session:
    bind = object()

    def __init__(self):
        self.rows = []

    def query(self, model):
        return _Query([row for row in self.rows if isinstance(row, model)])

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        return None


def test_binding_v04_is_selected_without_recovery_lookup(monkeypatch):
    binding = SimpleNamespace(
        effective_policy_version="g13-d-structural-autonomy-v0.4",
        binding_id="binding-v04",
        canonical_hash="0x" + "a" * 64,
        source_transition_id="transition-v04",
        recovery_event_id=None,
    )
    monkeypatch.setattr(runtime, "current_g13_policy_binding", lambda *args: binding)
    monkeypatch.setattr(runtime, "build_o_agent_stream", lambda *args: [])
    monkeypatch.setattr(runtime, "latest_operator_recovery", lambda *args: (_ for _ in ()).throw(AssertionError("selector lookup")))

    result = runtime.evaluate_current_g13(object(), "autonomy-controller")

    assert result.policy_version == "g13-d-structural-autonomy-v0.4"
    assert result.effective_policy_version == "g13-d-structural-autonomy-v0.4"
    assert result.policy_binding_id == "binding-v04"


def test_binding_version_never_downgrades_across_repeated_evaluations(monkeypatch):
    binding = SimpleNamespace(
        effective_policy_version="g13-d-structural-autonomy-v0.4",
        binding_id="binding-v04",
        canonical_hash="0x" + "b" * 64,
        source_transition_id="transition-v04",
        recovery_event_id="missing-recovery-row",
    )
    monkeypatch.setattr(runtime, "current_g13_policy_binding", lambda *args: binding)
    monkeypatch.setattr(runtime, "build_o_agent_stream", lambda *args: [])
    monkeypatch.setattr(runtime, "latest_operator_recovery", lambda *args: None)

    versions = [runtime.evaluate_current_g13(object(), "autonomy-controller").policy_version for _ in range(100)]

    assert versions == ["g13-d-structural-autonomy-v0.4"] * 100


def test_missing_binding_is_explicit_fail_closed():
    result = policy_binding_missing_evaluation("autonomy-controller")

    assert result.result == "HALT"
    assert result.triggered_rule_ids == (G13_POLICY_BINDING_MISSING,)
    assert result.result_core["failure_code"] == G13_POLICY_BINDING_MISSING
    assert "v0.2" not in result.policy_version


def test_transition_updates_binding_atomically_and_rejects_implicit_downgrade():
    session = _Session()
    activated = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    first = activate_g13_policy_binding(
        session,
        agent_id="autonomy-controller",
        effective_policy_version="g13-d-structural-autonomy-v0.4",
        previous_policy_version="g13-d-structural-autonomy-v0.3",
        source_transition_type="G13_RECOVERY_EVENT",
        source_transition_id="recovery-v04",
        recovery_event_id="recovery-v04",
        activated_at=activated,
    )
    second = activate_g13_policy_binding(
        session,
        agent_id="autonomy-controller",
        effective_policy_version="g13-d-structural-autonomy-v0.5",
        previous_policy_version="g13-d-structural-autonomy-v0.4",
        source_transition_type="G13_RECOVERY_EVENT",
        source_transition_id="recovery-v05",
        recovery_event_id="recovery-v05",
        activated_at=activated,
    )

    assert first is second
    assert second.effective_policy_version == "g13-d-structural-autonomy-v0.5"
    assert second.previous_policy_version == "g13-d-structural-autonomy-v0.4"
    with pytest.raises(ValueError, match="DOWNGRADE"):
        activate_g13_policy_binding(
            session,
            agent_id="autonomy-controller",
            effective_policy_version="g13-d-structural-autonomy-v0.2",
            previous_policy_version="g13-d-structural-autonomy-v0.5",
            source_transition_type="LEGACY",
            source_transition_id="implicit-downgrade",
            activated_at=activated,
        )


def test_policy_replay_preserves_binding_provenance():
    observations = []
    input_value = G13PolicyInput.from_observations("autonomy-controller", observations, allow_sparse_window=True)
    first = evaluate_g13_policy(input_value)
    bound = first.__class__(
        **{
            **first.__dict__,
            "effective_policy_version": "g13-d-structural-autonomy-v0.4",
            "policy_binding_id": "binding-v04",
            "policy_binding_hash": "0x" + "c" * 64,
            "source_transition_id": "transition-v04",
            "recovery_event_id": "recovery-v04",
        }
    )
    replayed = replay_policy(bound, lambda: bound)
    assert replayed.effective_policy_version == "g13-d-structural-autonomy-v0.4"
    with pytest.raises(ValueError, match="POLICY_REPLAY_MISMATCH"):
        replay_policy(bound, lambda: first)


def test_bound_evaluation_gets_append_only_identity_distinct_from_legacy():
    observations = []
    legacy = evaluate_g13_policy(
        G13PolicyInput.from_observations("autonomy-controller", observations, allow_sparse_window=True)
    )
    bound = legacy.__class__(
        **{
            **legacy.__dict__,
            "effective_policy_version": "g13-d-structural-autonomy-v0.4",
            "policy_binding_id": "binding-v04",
            "policy_binding_hash": "0x" + "d" * 64,
            "source_transition_id": "transition-v04",
            "recovery_event_id": "recovery-v04",
        }
    )
    assert bound.replay_identity != legacy.replay_identity
    assert bound.orm_values()["policy_binding_id"] == "binding-v04"
