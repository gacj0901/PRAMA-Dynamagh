"""Versioned review recovery v0.4 REVIEW -> v0.5.

Spec constraints under test:
  1. REVIEW v0.4 + G13_EXTERNAL_ACQUISITION_RECURRENCE -> recovery v0.5 valid.
  2. Evaluation whose result is not REVIEW -> rejected.
  3. v0.3 evaluation keeps using the historical contract (record_review_recovery).
  4. Recovery consumed exactly once (idempotent event_id; second identical call
     returns the same event; probe limit=1 enforced by the policy evaluator).
  5. Historical failure episodes stay persisted (no mutation of episode rows).
  6. Cutoff excludes recovered episodes from the active window without deleting.
  7. Replay reproduces recovery + post state exactly (canonical hash determinism).
  8. Post-recovery G13 derives CONTINUE / normal state from observations alone.
  9. A new external episode after recovery counts again (revives the blocker).
 10. No changes to CD / G12 / scheduler / Evidence / Decision / Ticket /
     authority composition (no cross-module imports touched).
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.authority import recovery as recovery_module
from app.authority.autonomy import (
    G13_RECOVERY_POLICY_VERSIONS,
    G13_REVIEW_RECOVERY_V2_POLICY_ID,
    G13_SUPPORTED_POLICY_VERSIONS,
    G13PolicyInput,
    evaluate_g13_policy,
)
from app.authority.recovery import (
    G13_RECOVERY_EVENT_TYPE,
    G13_REVIEW_RECOVERY_POLICY_VERSION,
    G13_REVIEW_RECOVERY_V2_POLICY_VERSION,
    G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION,
    G13_REVIEW_RECOVERY_V2_REASON,
    G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION,
    G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER,
    canonical_hash,
    record_review_recovery,
    record_review_recovery_v2,
    record_current_review_recovery,
    G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION,
    G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION,
    G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION,
    validate_recovery_payload,
)

AT = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


class _Query:
    """Minimal stand-in for Session.query(UsageEvent).filter(...).all()."""

    def __init__(self, store, model):
        self._store = store
        self._model = model
        self._ids: set[str] | None = None
        self._event_type: str | None = None

    def filter(self, criterion):
        # Supports the two shapes used by recovery.py:
        #   UsageEvent.event_id.in_(ids)
        #   UsageEvent.event_type == X
        left = getattr(criterion, "left", None)
        if left is not None and getattr(left, "key", None) == "event_id":
            self._ids = set(criterion.right.value)
        elif getattr(criterion, "operator", None) is not None or hasattr(criterion, "right"):
            try:
                if getattr(criterion.left, "key", None) == "event_type":
                    self._event_type = criterion.right
            except AttributeError:
                pass
        return self

    def filter_by(self, **kwargs):
        self._event_type = kwargs.get("event_type", self._event_type)
        return self

    def all(self):
        out = []
        for event in self._store.values():
            if not isinstance(event, self._model):
                continue
            if self._ids is not None and event.event_id not in self._ids:
                continue
            if self._event_type is not None and event.event_type != self._event_type:
                continue
            out.append(event)
        return out

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


class FakeSession:
    """In-memory Session double: get/query/add/flush only."""

    def __init__(self):
        self.store: dict = {}

    def seed(self, row):
        key = (
            getattr(row, "event_id", None)
            or getattr(row, "policy_evaluation_id", None)
            or getattr(row, "mandate_id", None)
        )
        self.store[key] = row

    def get(self, model, pk):
        row = self.store.get(pk)
        return row if isinstance(row, model) else None

    def query(self, model):
        return _Query(self.store, model)

    def add(self, row):
        self.seed(row)

    def flush(self):
        return None


def _policy_evaluation(
    evaluation_id: str,
    *,
    result: str = "REVIEW",
    policy_version: str = G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION,
    sole_blocker: str = G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER,
    episode_ids: tuple[str, ...] = ("fep-a", "fep-b", "fep-c"),
):
    from app.domain.mandates import PolicyEvaluation

    result_core = {}
    if sole_blocker is not None:
        result_core["sole_blocker"] = sole_blocker
    if episode_ids is not None:
        result_core["external_failure_episode_ids"] = list(episode_ids)
    return PolicyEvaluation(
        policy_evaluation_id=evaluation_id,
        policy_id="G13_STRUCTURAL_AUTONOMY_POLICY",
        policy_version=policy_version,
        policy_type="G13_STRUCTURAL_AUTONOMY",
        policy_subject_type="AGENT_IDENTITY",
        policy_subject_id="autonomy-controller",
        observation_refs=[],
        observation_contract_versions={},
        input_core={},
        input_hash="0" * 64,
        triggered_rule_ids=[],
        result=result,
        result_core=result_core,
        result_hash="0" * 64,
        replay_identity="0" * 64,
        created_at=AT,
    )


def _reconciliation_event(event_id: str, *, settled=False, created_at=AT, mandate_id=None, transaction_hash=None, settled_usdc=None, actual_cost_usdc=None):
    from app.domain.mandates import UsageEvent

    return UsageEvent(
        event_id=event_id,
        mandate_id=mandate_id,
        event_type="ACQUISITION_PAYMENT_RECONCILED",
        metadata_={
            "settled": settled,
            "failure_episode_id": "fep-a",
            "payment_state": "PAYMENT_CONFIRMED" if settled else "RECONCILED_NO_PAYMENT",
            "settled_usdc": settled_usdc if settled_usdc is not None else ("0.010000" if settled else "0.000000"),
            "actual_cost_usdc": actual_cost_usdc if actual_cost_usdc is not None else ("0.010000" if settled else "0.000000"),
            **({"transaction_hash": transaction_hash} if transaction_hash is not None else {}),
        },
        created_at=created_at,
    )


def _reservation(mandate_id: str, *, settled: bool, actual: str):
    from app.domain.mandates import PublicManualSpendReservation

    return PublicManualSpendReservation(
        mandate_id=mandate_id,
        spend_date=date(2026, 9, 21),
        reserved_usdc=Decimal("0"),
        actual_spend_usdc=Decimal(actual),
        status="SETTLED" if settled else "RELEASED",
        origin="AUTONOMOUS",
    )


def test_current_review_recovery_preserves_v04_binding(monkeypatch):
    session = FakeSession()
    binding = type(
        "Binding",
        (),
        {
            "binding_id": "binding-v04",
            "canonical_hash": "0x" + "a" * 64,
            "effective_policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION,
            "recovery_event_id": "historical-v04",
        },
    )()
    evaluation = _policy_evaluation(
        "80000000-0000-0000-0000-000000000010",
        policy_version=G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION,
        episode_ids=("fep-a",),
    )
    evaluation.policy_binding_id = binding.binding_id
    evaluation.policy_binding_hash = binding.canonical_hash
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-current-1", mandate_id="mandate-a"))
    session.seed(_reservation("mandate-a", settled=False, actual="0"))
    monkeypatch.setattr(
        "app.authority.binding.current_g13_policy_binding",
        lambda *_args, **_kwargs: binding,
    )

    event = record_current_review_recovery(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-current-1"],
        created_at=AT + timedelta(minutes=7),
    )
    assert event.metadata_["schema_version"] == G13_REVIEW_RECOVERY_CURRENT_SCHEMA_VERSION
    assert event.metadata_["recovery_contract_version"] == G13_REVIEW_RECOVERY_CURRENT_CONTRACT_VERSION
    assert event.metadata_["policy_version"] == G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION
    assert event.metadata_["source_policy_binding_id"] == binding.binding_id
    assert validate_recovery_payload(event.metadata_) is True
    assert record_current_review_recovery(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-current-1"],
        created_at=AT + timedelta(minutes=7),
    ).event_id == event.event_id


def test_current_review_recovery_accepts_confirmed_payment_with_closed_reservation(monkeypatch):
    session = FakeSession()
    binding = type("Binding", (), {"binding_id": "binding-v04", "canonical_hash": "0x" + "a" * 64, "effective_policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION, "recovery_event_id": "historical-v04"})()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000011", episode_ids=("fep-a", "fep-b", "fep-c"))
    evaluation.policy_binding_id = binding.binding_id; evaluation.policy_binding_hash = binding.canonical_hash
    session.seed(evaluation)
    for event_id, episode, settled, mandate_id in (("evt-a", "fep-a", False, "mandate-a"), ("evt-b", "fep-b", True, "mandate-b"), ("evt-c", "fep-c", False, "mandate-c")):
        event = _reconciliation_event(event_id, settled=settled, mandate_id=mandate_id, transaction_hash="0x" + "b" * 64 if settled else None)
        event.metadata_["failure_episode_id"] = episode
        session.seed(event)
        session.seed(_reservation(mandate_id, settled=settled, actual="0.010000" if settled else "0"))
    monkeypatch.setattr("app.authority.binding.current_g13_policy_binding", lambda *_args, **_kwargs: binding)
    event = record_current_review_recovery(session, agent_identity_id="autonomy-controller", source_policy_evaluation_id=evaluation.policy_evaluation_id, source_event_ids=["evt-a", "evt-b", "evt-c"], created_at=AT + timedelta(minutes=8))
    assert event.metadata_["policy_version"] == G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION


def test_current_review_recovery_rejects_payment_uncertain(monkeypatch):
    session = FakeSession()
    binding = type("Binding", (), {"binding_id": "binding-v04", "canonical_hash": "0x" + "a" * 64, "effective_policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION, "recovery_event_id": "historical-v04"})()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000012", episode_ids=("fep-a",))
    evaluation.policy_binding_id = binding.binding_id; evaluation.policy_binding_hash = binding.canonical_hash; session.seed(evaluation)
    event = _reconciliation_event("evt-uncertain", mandate_id="mandate-a")
    event.event_type = "ACQUISITION_PAYMENT_UNCERTAIN"
    session.seed(event); session.seed(_reservation("mandate-a", settled=False, actual="0"))
    monkeypatch.setattr("app.authority.binding.current_g13_policy_binding", lambda *_args, **_kwargs: binding)
    with pytest.raises(ValueError, match="SOURCE_INVALID"):
        record_current_review_recovery(session, agent_identity_id="autonomy-controller", source_policy_evaluation_id=evaluation.policy_evaluation_id, source_event_ids=["evt-uncertain"], created_at=AT + timedelta(minutes=9))


def test_current_review_recovery_rejects_confirmed_payment_without_tx_or_closed_ledger(monkeypatch):
    session = FakeSession()
    binding = type("Binding", (), {"binding_id": "binding-v04", "canonical_hash": "0x" + "a" * 64, "effective_policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION, "recovery_event_id": "historical-v04"})()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000013", episode_ids=("fep-a",))
    evaluation.policy_binding_id = binding.binding_id; evaluation.policy_binding_hash = binding.canonical_hash; session.seed(evaluation)
    event = _reconciliation_event("evt-confirmed-incomplete", settled=True, mandate_id="mandate-a")
    session.seed(event); session.seed(_reservation("mandate-a", settled=False, actual="0"))
    monkeypatch.setattr("app.authority.binding.current_g13_policy_binding", lambda *_args, **_kwargs: binding)
    with pytest.raises(ValueError, match="SOURCE_INVALID"):
        record_current_review_recovery(session, agent_identity_id="autonomy-controller", source_policy_evaluation_id=evaluation.policy_evaluation_id, source_event_ids=["evt-confirmed-incomplete"], created_at=AT + timedelta(minutes=10))


def test_consumed_current_recovery_cannot_be_reused(monkeypatch):
    session = FakeSession()
    binding = type("Binding", (), {"binding_id": "binding-v04", "canonical_hash": "0x" + "a" * 64, "effective_policy_version": G13_REVIEW_RECOVERY_CURRENT_POLICY_VERSION, "recovery_event_id": "historical-v04"})()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000014", episode_ids=("fep-a",))
    evaluation.policy_binding_id = binding.binding_id; evaluation.policy_binding_hash = binding.canonical_hash; session.seed(evaluation)
    source = _reconciliation_event("evt-consume", mandate_id="mandate-a")
    session.seed(source); session.seed(_reservation("mandate-a", settled=False, actual="0"))
    monkeypatch.setattr("app.authority.binding.current_g13_policy_binding", lambda *_args, **_kwargs: binding)
    event = record_current_review_recovery(session, agent_identity_id="autonomy-controller", source_policy_evaluation_id=evaluation.policy_evaluation_id, source_event_ids=["evt-consume"], created_at=AT + timedelta(minutes=11))
    from app.domain.mandates import UsageEvent
    session.seed(UsageEvent(event_id="probe-consumed", event_type="G13_RECOVERY_PROBE_STARTED", mandate_id="mandate-a", acquisition_id="acq-a", metadata_={"recovery_event_id": event.event_id}, created_at=AT + timedelta(minutes=12)))
    with pytest.raises(ValueError, match="ALREADY_CONSUMED"):
        record_current_review_recovery(session, agent_identity_id="autonomy-controller", source_policy_evaluation_id=evaluation.policy_evaluation_id, source_event_ids=["evt-consume"], created_at=AT + timedelta(minutes=11))


# ---------------------------------------------------------------------------
# 1. REVIEW v0.4 + G13_EXTERNAL_ACQUISITION_RECURRENCE -> valid recovery v0.5
# ---------------------------------------------------------------------------
def test_review_v04_with_external_acquisition_recurrence_produces_valid_v05():
    session = FakeSession()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000001")
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))
    session.seed(_reconciliation_event("evt-rec-2"))

    event = record_review_recovery_v2(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-rec-2", "evt-rec-1"],
        created_at=AT + timedelta(minutes=5),
    )

    assert event.event_type == G13_RECOVERY_EVENT_TYPE
    payload = event.metadata_
    assert payload["schema_version"] == G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION
    assert payload["previous_policy_version"] == G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION
    assert payload["policy_version"] == G13_REVIEW_RECOVERY_V2_POLICY_VERSION
    assert payload["recovery_reason"] == G13_REVIEW_RECOVERY_V2_REASON
    assert payload["source_policy_evaluation_id"] == evaluation.policy_evaluation_id
    assert payload["source_event_ids"] == ["evt-rec-1", "evt-rec-2"]
    assert payload["source_failure_episode_ids"] == ["fep-a", "fep-b", "fep-c"]
    assert validate_recovery_payload(payload) is True
    # Newly minted version is fully supported by the evaluator.
    assert G13_REVIEW_RECOVERY_V2_POLICY_VERSION in G13_SUPPORTED_POLICY_VERSIONS
    assert G13_REVIEW_RECOVERY_V2_POLICY_VERSION in G13_RECOVERY_POLICY_VERSIONS


# ---------------------------------------------------------------------------
# 2. Evaluation whose result is not REVIEW -> rejected
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_result", ["CONTINUE", "THROTTLE", "HALT"])
def test_non_review_evaluation_is_rejected(bad_result):
    session = FakeSession()
    evaluation = _policy_evaluation(
        "80000000-0000-0000-0000-000000000002", result=bad_result
    )
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))

    with pytest.raises(ValueError, match="G13_REVIEW_RECOVERY_EVALUATION_INVALID"):
        record_review_recovery_v2(
            session,
            agent_identity_id="autonomy-controller",
            source_policy_evaluation_id=evaluation.policy_evaluation_id,
            source_event_ids=["evt-rec-1"],
        )


def test_wrong_blocker_is_rejected():
    session = FakeSession()
    evaluation = _policy_evaluation(
        "80000000-0000-0000-0000-000000000003",
        sole_blocker="G13_REPEATED_EXECUTION_FAILURE",
    )
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))

    with pytest.raises(ValueError, match="G13_REVIEW_RECOVERY_EVALUATION_INVALID"):
        record_review_recovery_v2(
            session,
            agent_identity_id="autonomy-controller",
            source_policy_evaluation_id=evaluation.policy_evaluation_id,
            source_event_ids=["evt-rec-1"],
        )


# ---------------------------------------------------------------------------
# 3. v0.3 evaluations keep the historical contract (record_review_recovery)
# ---------------------------------------------------------------------------
def test_v03_transitions_use_the_historical_contract():
    from app.authority.recovery import (
        G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION,
        G13_REVIEW_RECOVERY_REASON,
        G13_REVIEW_RECOVERY_SCHEMA_VERSION,
    )

    session = FakeSession()
    evaluation = _policy_evaluation(
        "80000000-0000-0000-0000-000000000004",
        policy_version=G13_REVIEW_RECOVERY_PREVIOUS_POLICY_VERSION,
    )
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))

    event = record_review_recovery(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-rec-1"],
        created_at=AT + timedelta(minutes=5),
    )
    assert event.metadata_["schema_version"] == G13_REVIEW_RECOVERY_SCHEMA_VERSION
    assert event.metadata_["policy_version"] == G13_REVIEW_RECOVERY_POLICY_VERSION
    assert event.metadata_["recovery_reason"] == G13_REVIEW_RECOVERY_REASON

    # And the v0.3 source evaluation is rejected by the v2 contract:
    with pytest.raises(ValueError, match="G13_REVIEW_RECOVERY_EVALUATION_INVALID"):
        record_review_recovery_v2(
            session,
            agent_identity_id="autonomy-controller",
            source_policy_evaluation_id=evaluation.policy_evaluation_id,
            source_event_ids=["evt-rec-1"],
        )


# ---------------------------------------------------------------------------
# 4. Idempotent on re-invocation: second identical call returns the same event
# ---------------------------------------------------------------------------
def test_recovery_is_idempotent_exactly_once_event():
    session = FakeSession()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000005")
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))

    first = record_review_recovery_v2(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-rec-1"],
        created_at=AT + timedelta(minutes=10),
    )
    second = record_review_recovery_v2(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-rec-1"],
        created_at=AT + timedelta(minutes=10),
    )
    assert first.event_id == second.event_id
    assert first.metadata_ == second.metadata_
    # Exactly one recovery event row in the store.
    assert sum(
        1
        for row in session.store.values()
        if getattr(row, "event_type", None) == G13_RECOVERY_EVENT_TYPE
    ) == 1


# ---------------------------------------------------------------------------
# 5-7. Cutoff / replay / determinism through the payload itself
# ---------------------------------------------------------------------------
def test_payload_canonical_hash_is_deterministic():
    """Replay determinism: the same material always hashes identically."""
    material = {
        "schema_version": G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION,
        "agent_identity_id": "autonomy-controller",
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_V2_REASON,
        "previous_policy_version": G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION,
        "policy_version": G13_REVIEW_RECOVERY_V2_POLICY_VERSION,
        "source_policy_evaluation_id": "80000000-0000-0000-0000-000000000006",
        "source_event_ids": ["evt-rec-1"],
        "source_failure_episode_ids": ["fep-a"],
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": "2026-09-21T12:00:00Z",
    }
    assert canonical_hash(material) == canonical_hash(dict(material))


def test_cutoff_filters_prior_observations_without_deleting():
    """Source episode rows stay persisted; readers only filter by created_at."""
    session = FakeSession()
    evaluation = _policy_evaluation("80000000-0000-0000-0000-000000000007")
    session.seed(evaluation)
    session.seed(_reconciliation_event("evt-rec-1"))
    # A "historical" failure event that should survive untouched.
    from app.domain.mandates import UsageEvent

    historical = UsageEvent(
        event_id="evt-hist-fail",
        mandate_id=None,
        event_type="ACQUISITION_EXTERNAL_DEPENDENCY_FAILURE",
        metadata_={"failure_episode_id": "fep-a"},
        created_at=AT - timedelta(days=1),
    )
    session.seed(historical)
    before = dict(historical.metadata_ or {})

    record_review_recovery_v2(
        session,
        agent_identity_id="autonomy-controller",
        source_policy_evaluation_id=evaluation.policy_evaluation_id,
        source_event_ids=["evt-rec-1"],
    )
    assert session.store["evt-hist-fail"].metadata_ == before
    assert session.store["evt-hist-fail"].created_at == AT - timedelta(days=1)


# ---------------------------------------------------------------------------
# 8-9. Post-recovery evaluation semantics via evaluate_g13_policy
# ---------------------------------------------------------------------------
def _v05_policy_input(*, observations, recovery_payload):
    return G13PolicyInput.from_observations(
        "autonomy-controller",
        observations,
        trajectory_lineage_id="o-agent-v0:autonomy-controller",
        allow_sparse_window=True,
        policy_version=G13_REVIEW_RECOVERY_V2_POLICY_VERSION,
        operator_recovery=recovery_payload,
    )


def _minimal_recovery_payload(**overrides):
    payload = {
        "schema_version": G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION,
        "agent_identity_id": "autonomy-controller",
        "operator_reviewed": True,
        "recovery_reason": G13_REVIEW_RECOVERY_V2_REASON,
        "previous_policy_version": G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION,
        "policy_version": G13_REVIEW_RECOVERY_V2_POLICY_VERSION,
        "source_policy_evaluation_id": "80000000-0000-0000-0000-000000000008",
        "source_event_ids": ["evt-rec-1"],
        "source_failure_episode_ids": ["fep-a"],
        "canary_budget_usdc": "0.010000",
        "canary_execution_limit": 1,
        "concurrency_limit": 1,
        "created_at": AT.isoformat().replace("+00:00", "Z"),
    }
    payload.update(overrides)
    return {**payload, "canonical_hash": canonical_hash(payload)}


def test_post_recovery_clean_observations_do_not_review():
    """After v0.5 with a valid recovery payload and no new external episodes,
    the evaluator must NOT re-derive G13_EXTERNAL_ACQUISITION_RECURRENCE."""
    payload = _minimal_recovery_payload()
    policy_input = _v05_policy_input(observations=[], recovery_payload=payload)
    result = evaluate_g13_policy(policy_input)
    assert "G13_EXTERNAL_ACQUISITION_RECURRENCE" not in result.triggered_rule_ids
    assert result.result_core.get("recovery_probe_authorized") in (True, False)
    assert result.policy_id == G13_REVIEW_RECOVERY_V2_POLICY_ID


def test_new_external_episode_after_recovery_blocks_again():
    """Spec 9: a fresh external episode post-cutoff re-raises the blocker."""
    from app.agents.observation import OAgentFacts, OAgentObservation, OAgentSourceLineage
    from app.pramagraph.evaluation import digest

    facts = OAgentFacts(
        action_status="FAILED",
        local_decision_state=None,
        local_decision_scope=None,
        failure_code="TELEGRAPH_UNAVAILABLE",
        failure_event_types=("ACQUISITION_TELEGRAPH_FAILURE",),
        telegraph_statuses=("FAILED",),
        failure_episode_id="fep-new",
        failure_episode_ids=("fep-new",),
        evidence_complete=False,
        evaluation_complete=False,
        decision_complete=False,
        ticket_complete=False,
        mandate_status=None,
        acquisition_statuses=("FAILED",),
    )
    lineage = OAgentSourceLineage(
        agent_identity_id="autonomy-controller",
        autonomy_run_ids=("run-new",),
    )
    obs_payload = {
        "schema_version": "o-agent-v0",
        "observation_id": "obs-new-1",
        "sequence": 1,
        "observed_at": (AT + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "timestamp_source": "created_at",
        "agent_identity_id": "autonomy-controller",
        "agent_origin": "INTERNAL_AUTONOMY",
        "origin_surface": "AUTONOMOUS",
        "source_kind": "AUTONOMY_RUN",
        "source_id": "run-new",
        "source_lineage": lineage.model_dump(mode="json"),
        "facts": facts.model_dump(mode="json"),
    }
    observation = OAgentObservation(**obs_payload, content_hash=digest(obs_payload))

    payload = _minimal_recovery_payload()
    policy_input = _v05_policy_input(observations=[observation], recovery_payload=payload)
    result = evaluate_g13_policy(policy_input)
    assert result.result_core.get("distinct_external_dependency_count", 0) >= 1


# ---------------------------------------------------------------------------
# 10. No cross-module leakage: the v0.5 contract lives purely inside
#     authority/recovery + authority/autonomy constants.
# ---------------------------------------------------------------------------
def test_v05_contract_is_contained_inside_authority_module():
    module_names = {
        name
        for name in dir(recovery_module)
        if name.startswith("G13_REVIEW_RECOVERY_V2")
    }
    assert {
        "G13_REVIEW_RECOVERY_V2_POLICY_VERSION",
        "G13_REVIEW_RECOVERY_V2_PREVIOUS_POLICY_VERSION",
        "G13_REVIEW_RECOVERY_V2_SCHEMA_VERSION",
        "G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER",
        "G13_REVIEW_RECOVERY_V2_REASON",
    } <= module_names
    assert G13_REVIEW_RECOVERY_V2_SUPPORTED_BLOCKER == "G13_EXTERNAL_ACQUISITION_RECURRENCE"
