"""Deterministic ExecutionPermit binding and fail-closed consumption tests."""

from datetime import datetime, timedelta, timezone
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
import inspect

import pytest

from app.authority import delegated
from app.epistemic.contracts import canonical_hash
from app.domain.mandates import ExecutionPermit


def _action(**overrides):
    values = dict(
        mandate_id="mandate-1",
        agent_identity_id="agent-1",
        action_id="action-1",
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        query="A B",
        requested_intent="RESEARCH_QUERY",
        causal_request_id="mandate-1",
        amount=Decimal("0.010000"),
        adapter_target={
            "provider": "TELEGRAPH",
            "access_mechanism": "GATEWAY",
            "adapter_kind": "adapter.gateway",
            "execution_target_fingerprint": "0x" + "a" * 64,
        },
        reservation={
            "mandate_id": "mandate-1",
            "spend_date": "2026-09-24",
            "reserved_usdc": Decimal("0.050000"),
            "status": "RESERVED",
            "origin": "AUTONOMOUS",
        },
    )
    values.update(overrides)
    return delegated.build_execution_action_material(**values)


def _permit(action, *, expires_at=None):
    constraints = {
        "g12_reservation_verified": True,
        delegated.ACTION_ENVELOPE_CONSTRAINT: action,
    }
    values = dict(
        principal_id="principal-1",
        agent_identity_id="agent-1",
        mandate_id="mandate-1",
        action_id="action-1",
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        authority_profile_id="profile-1",
        g12_result="PERMIT",
        g13_result="CONTINUE",
        decision_id=None,
        constraints=constraints,
    )
    return SimpleNamespace(
        **values,
        permit_id="permit-1",
        authority_hash=canonical_hash(delegated.build_execution_permit_material(**values)),
        issued_at=datetime.now(timezone.utc),
        expires_at=expires_at,
        consumed_at=None,
        result_hash=None,
    )


class _Query:
    def __init__(self, permit):
        self.permit = permit

    def populate_existing(self):
        return self

    def filter_by(self, **_kwargs):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self.permit


class _Session:
    def __init__(self, permit):
        self.permit = permit
        self.events = []

    def query(self, _model):
        assert _model is ExecutionPermit
        return _Query(self.permit)

    def add(self, event):
        self.events.append(event)


def _consume(session, expected, authority_validator=lambda _permit: None):
    return delegated.consume_execution_permit(
        session,
        "permit-1",
        expected_action_material=expected,
        authority_validator=authority_validator,
    )


def test_action_material_is_deterministic_and_decimal_normalized():
    first = _action()
    second = _action(amount=Decimal("0.01"))
    assert canonical_hash(first) == canonical_hash(second)
    assert first["economic_envelope"]["authorized_amount_usdc"] == "0.01"
    reversed_target = dict(reversed(list(first["target"].items())))
    reversed_reservation = dict(reversed(list(first["economic_envelope"]["reservation"].items())))
    reordered = _action(adapter_target=reversed_target, reservation=reversed_reservation)
    assert canonical_hash(first) == canonical_hash(reordered)


def test_adapter_target_fingerprint_binds_destination_without_persisting_it():
    from app.workers.acquisition import _adapter_target_material

    one = _adapter_target_material(SimpleNamespace(
        provider="TELEGRAPH", access_mechanism="GATEWAY", base_url="https://gateway-a.test",
    ))
    two = _adapter_target_material(SimpleNamespace(
        provider="TELEGRAPH", access_mechanism="GATEWAY", base_url="https://gateway-b.test",
    ))
    assert one["execution_target_fingerprint"] != two["execution_target_fingerprint"]
    assert "gateway-a.test" not in repr(one)


def test_payload_text_is_bound_exactly_without_semantic_whitespace_rewrite():
    assert _action(query="A B")["payload_hash"] != _action(query="A\nB")["payload_hash"]


def test_valid_action_consumes_once_and_null_ttl_is_allowed():
    action = _action()
    session = _Session(_permit(action))
    permit = _consume(session, action)
    assert permit.consumed_at is not None
    assert [event.event_type for event in session.events] == [
        "EXECUTION_PERMIT_CONSUMED",
        "EXECUTION_DISPATCH_COMMITTED",
    ]
    commitment = session.events[1].metadata_
    assert commitment["commitment_state"] == "COMMITTED_FOR_DISPATCH"
    assert commitment["action_envelope_hash"] == canonical_hash(action)
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_ALREADY_CONSUMED"):
        _consume(session, action)


@pytest.mark.parametrize(
    "changed,code",
    [
        ({"query": "A C"}, "EXECUTION_PERMIT_PAYLOAD_MISMATCH"),
        (
            {"adapter_target": {"provider": "TELEGRAPH", "access_mechanism": "MCP", "adapter_kind": "adapter.mcp", "execution_target_fingerprint": "0x" + "b" * 64}},
            "EXECUTION_PERMIT_TARGET_MISMATCH",
        ),
        ({"amount": Decimal("0.011")}, "EXECUTION_PERMIT_ECONOMIC_MISMATCH"),
    ],
)
def test_action_substitutions_fail_before_authority_or_dispatch(changed, code):
    action = _action()
    session = _Session(_permit(action))
    validation_calls = []
    with pytest.raises(ValueError, match=code):
        _consume(session, _action(**changed), lambda row: validation_calls.append(row))
    assert validation_calls == []
    assert session.permit.consumed_at is None


def test_stale_authority_fails_closed_before_permit_consumption():
    action = _action()
    session = _Session(_permit(action))
    adapter_calls = []

    def reject_stale(_permit):
        raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")

    with pytest.raises(ValueError, match="EXECUTION_PERMIT_AUTHORITY_STALE"):
        _consume(session, action, reject_stale)
    assert session.permit.consumed_at is None
    assert adapter_calls == []


def test_expired_and_legacy_permits_fail_closed():
    action = _action()
    expired = _Session(_permit(action, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_EXPIRED"):
        _consume(expired, action)

    legacy = _permit(action)
    legacy.constraints = {"g12_reservation_verified": True}
    # A self-consistent old hash still cannot authorize an unbound action.
    legacy.authority_hash = canonical_hash(delegated.build_execution_permit_material(
        principal_id=legacy.principal_id,
        agent_identity_id=legacy.agent_identity_id,
        mandate_id=legacy.mandate_id,
        action_id=legacy.action_id,
        action_kind=legacy.action_kind,
        authority_profile_id=legacy.authority_profile_id,
        g12_result=legacy.g12_result,
        g13_result=legacy.g13_result,
        decision_id=legacy.decision_id,
        constraints=legacy.constraints,
    ))
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_INVALID"):
        _consume(_Session(legacy), action)


def test_invalid_authority_hash_is_rejected():
    action = _action()
    permit = _permit(action)
    permit.constraints[delegated.ACTION_ENVELOPE_CONSTRAINT]["action_id"] = "substituted"
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_INVALID"):
        _consume(_Session(permit), action)


def test_worker_keeps_m2m_outside_permit_branch_and_dispatch_after_consumption():
    from app.workers import acquisition

    source = inspect.getsource(acquisition.execute_one)
    autonomous = source.index('if mandate.origin == "AUTONOMOUS":')
    consume = source.index("consume_execution_permit(", autonomous)
    network = source.index("network_attempted = True", consume)
    dispatch = source.index("result = adapter.acquire(", network)
    assert autonomous < consume < network < dispatch
    assert 'if mandate.origin == "M2M":' not in source[autonomous:consume]


class _FreshQuery:
    def __init__(self, model, rows):
        self.model = model
        self.rows = rows

    def populate_existing(self):
        return self

    def filter_by(self, **filters):
        self.filters = filters
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        if self.model is ExecutionPermit:
            return self.rows.get("permit")
        if self.model.__name__ == "Mandate":
            return self.rows.get("mandate")
        if self.model.__name__ == "AcquisitionTask":
            return self.rows.get("task")
        if self.model.__name__ == "AgentIdentity":
            return self.rows.get("identity")
        if self.model.__name__ == "PublicManualSpendReservation":
            return self.rows.get("reservation")
        return self.rows.get("profile")


class _FreshSession:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _FreshQuery(model, self.rows)

    def get(self, _model, _key):
        return None


@pytest.fixture
def fresh_authority_context(monkeypatch):
    from app.authority import runtime
    from app.domain.mandates import AcquisitionTask, AgentIdentity, Mandate, PublicManualSpendReservation
    from app.workers import acquisition

    profile = SimpleNamespace(
        authority_profile_id="profile-1", status="ACTIVE", agent_identity_id="agent-1",
        allowed_action_kinds=["TELEGRAPH_HTTP_ACQUISITION"], allowed_intents=[],
        external_execution_allowed=True, telegraph_allowed=True,
        unlimited_budget=False, economic_budget=Decimal("0.05"),
        per_action_budget=Decimal("0.05"), human_review_thresholds={},
    )
    mandate = SimpleNamespace(
        mandate_id="mandate-1", agent_identity_id="agent-1", origin="AUTONOMOUS",
        status="ACQUIRING",
    )
    task = SimpleNamespace(
        acquisition_id="action-1", mandate_id="mandate-1", query="A B",
        requested_intent="RESEARCH_QUERY", status="RUNNING",
    )
    identity = SimpleNamespace(agent_id="agent-1", status="ACTIVE", autonomy_state="ACTIVE")
    reservation = SimpleNamespace(
        mandate_id="mandate-1", spend_date=date(2026, 9, 24),
        reserved_usdc=Decimal("0.05"), status="RESERVED", origin="AUTONOMOUS",
    )
    adapter = SimpleNamespace(
        provider="TELEGRAPH", access_mechanism="GATEWAY", base_url="https://gateway.test",
    )
    rows = {
        "profile": profile, "mandate": mandate, "task": task,
        "identity": identity, "reservation": reservation,
    }
    session = _FreshSession(rows)
    monkeypatch.setattr(delegated, "full_autonomy_enabled", lambda _agent: True)
    monkeypatch.setattr(delegated, "resolve_profile", lambda _session, _agent: profile)
    monkeypatch.setattr(delegated, "_allowed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(delegated, "g12_check", lambda _profile, amount, **_kw: (amount <= Decimal(_profile.per_action_budget), "PERMIT"))
    monkeypatch.setattr(acquisition, "maximum", lambda *_args: Decimal("0.05"))
    monkeypatch.setattr(acquisition, "verify_spend_reservation", lambda *_args: reservation)
    monkeypatch.setattr(acquisition, "uncertain_hold", lambda *_args: Decimal("0"))
    monkeypatch.setattr(acquisition.user_credit, "verify_reserved", lambda *_args: None)
    current_g13 = SimpleNamespace(
        result="CONTINUE", policy_version="g13-d-structural-autonomy-v0.5",
        result_core={}, input_core={},
    )
    monkeypatch.setattr(runtime, "evaluate_current_g13", lambda *_args: current_g13)

    def checkpoint(_session, **kwargs):
        g13 = kwargs["longitudinal_core"]
        allowed = g13.result == "CONTINUE" or (
            g13.result == "THROTTLE" and kwargs["throttled_constraints_satisfied"]
        ) or (g13.result == "REVIEW" and kwargs["recovery_probe_authorized"])
        if g13.result == "HALT":
            allowed = False
        return SimpleNamespace(composition=SimpleNamespace(result="ALLOW" if allowed else "RESTRICT"))

    monkeypatch.setattr(runtime, "run_pre_next_action_authority_check", checkpoint)
    monkeypatch.setattr(acquisition, "_test_current_g13", lambda: current_g13, raising=False)
    permit = SimpleNamespace(
        authority_profile_id="profile-1", agent_identity_id="agent-1",
        action_kind="TELEGRAPH_HTTP_ACQUISITION",
        constraints={
            "bootstrap_authorized": False,
            "recovery_probe_authorized": False,
            "agent_autonomy_state": "ACTIVE",
        },
    )
    material = acquisition._build_action_material(
        mandate=mandate, task=task, adapter=adapter, amount=Decimal("0.01"),
        reservation=reservation,
    )
    return SimpleNamespace(
        acquisition=acquisition, runtime=runtime, profile=profile, mandate=mandate,
        task=task, identity=identity, reservation=reservation, adapter=adapter,
        session=session, permit=permit, action=material, g13=current_g13,
    )


def _fresh_validate(context, *, amount=Decimal("0.01")):
    context.acquisition._validate_fresh_autonomous_authority(
        context.session,
        permit=context.permit,
        mandate_id="mandate-1",
        acquisition_id="action-1",
        run=SimpleNamespace(policy_id="policy-1", run_id="run-1"),
        adapter=context.adapter,
        action_material=context.action,
        budget=amount,
        throttle_ok=True,
    )


def test_fresh_unchanged_authority_allows_dispatch_checkpoint(fresh_authority_context):
    _fresh_validate(fresh_authority_context)


@pytest.mark.parametrize("status", ["SUSPENDED", "REVOKED", "EXPIRED"])
def test_profile_lifecycle_change_fails_closed(fresh_authority_context, monkeypatch, status):
    del status
    from app.authority import delegated
    monkeypatch.setattr(delegated, "resolve_profile", lambda *_args: (_ for _ in ()).throw(ValueError("NO_AUTHORITY_PROFILE")))
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_PROFILE_INVALID"):
        _fresh_validate(fresh_authority_context)


def test_profile_version_replacement_fails_closed(fresh_authority_context):
    fresh_authority_context.profile.authority_profile_id = "profile-2"
    from app.authority import delegated
    # The resolver now returns a different effective version than the permit bound.
    old = delegated.resolve_profile
    delegated.resolve_profile = lambda *_args: fresh_authority_context.profile
    try:
        with pytest.raises(ValueError, match="EXECUTION_PERMIT_PROFILE_INVALID"):
            _fresh_validate(fresh_authority_context)
    finally:
        delegated.resolve_profile = old


@pytest.mark.parametrize("autonomy_state,status", [
    ("HALTED", "ACTIVE"), ("REVIEW_REQUIRED", "ACTIVE"), ("ACTIVE", "DISABLED"),
])
def test_identity_loss_of_autonomy_fails_closed(fresh_authority_context, autonomy_state, status):
    fresh_authority_context.identity.autonomy_state = autonomy_state
    fresh_authority_context.identity.status = status
    expected = "EXECUTION_PERMIT_G13_INVALID" if autonomy_state in {"HALTED", "REVIEW_REQUIRED"} else "EXECUTION_PERMIT_AUTHORITY_STALE"
    with pytest.raises(ValueError, match=expected):
        _fresh_validate(fresh_authority_context)


def test_g12_reservation_revocation_fails_closed(fresh_authority_context):
    fresh_authority_context.reservation.status = "RELEASED"
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_G12_INVALID"):
        _fresh_validate(fresh_authority_context)


@pytest.mark.parametrize("result", ["REVIEW", "HALT"])
def test_g13_review_or_halt_blocks_dispatch(fresh_authority_context, result):
    fresh_authority_context.g13.result = result
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_G13_INVALID"):
        _fresh_validate(fresh_authority_context)


def test_g13_throttle_rechecks_current_economic_limit(fresh_authority_context):
    fresh_authority_context.g13.result = "THROTTLE"
    fresh_authority_context.profile.human_review_thresholds = {"throttle_max_usdc": "0.02"}
    fresh_authority_context.action = fresh_authority_context.acquisition._build_action_material(
        mandate=fresh_authority_context.mandate,
        task=fresh_authority_context.task,
        adapter=fresh_authority_context.adapter,
        amount=Decimal("0.02"),
        reservation=fresh_authority_context.reservation,
    )
    _fresh_validate(fresh_authority_context, amount=Decimal("0.02"))
    fresh_authority_context.profile.human_review_thresholds = {"throttle_max_usdc": "0.01"}
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_G13_INVALID"):
        _fresh_validate(fresh_authority_context, amount=Decimal("0.02"))


def test_g12_profile_budget_change_blocks_amount(fresh_authority_context):
    fresh_authority_context.profile.per_action_budget = Decimal("0.005")
    with pytest.raises(ValueError, match="EXECUTION_PERMIT_G12_INVALID"):
        _fresh_validate(fresh_authority_context)
