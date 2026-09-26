from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.api.public_surfaces import public_activity, public_ticket_summary


class Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def count(self):
        return len(self.rows)


class Session:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return Query(self.rows.get(model, []))

    def get(self, model, key):
        return next((row for row in self.rows.get(model, []) if getattr(row, "ticket_id", None) == key), None)


def test_public_activity_is_aggregate_only_and_origin_scoped():
    from app.domain.mandates import AcquisitionTask, AutonomyRun, Decision, Evidence, Mandate, StructuralEvaluation, TelegraphCall, Ticket

    manual = SimpleNamespace(mandate_id="m1", actor_id="human", origin="MANUAL", status="TICKETED")
    autonomous = SimpleNamespace(mandate_id="a1", actor_id="internal", origin="AUTONOMOUS", status="TICKETED")
    call = SimpleNamespace(mandate_id="m1", status="SUCCEEDED", miner_id="miner-1", intent="CRYPTO_PRICE", duration_ms=120, cost_usd=Decimal("0.001"))
    session = Session({
        Mandate: [manual, autonomous],
        AcquisitionTask: [], TelegraphCall: [call], Evidence: [], Decision: [], Ticket: [], AutonomyRun: [object()], StructuralEvaluation: [],
    })

    result = public_activity(session)

    assert result["workflows_started"] == 1
    assert result["real_users"] == 1
    assert result["autonomous_runs"] == 1
    assert result["public_spend_usdc"] == "0.001000"
    assert result["scope"]["test_classification"] == "NOT_PERSISTED_SEPARATELY"
    assert result["budget_profile"]["effective_max_usdc_per_workflow"] == "0.050000"
    assert result["budget_profile"]["max_real_calls_per_workflow"] == 5
    assert result["budget_profile"]["multi_intent_enabled"] is True


def test_public_activity_exposes_authenticated_m2m_requester_principal():
    from app.domain.mandates import AcquisitionTask, AutonomyRun, Decision, Evidence, Mandate, StructuralEvaluation, TelegraphCall, Ticket

    m2m = SimpleNamespace(mandate_id="m2m-1", actor_id="m2m:telegraph:agent", origin="M2M", status="RECEIVED", client_id="TELEGRAPH")
    session = Session({
        Mandate: [m2m],
        AcquisitionTask: [], TelegraphCall: [], Evidence: [], Decision: [], Ticket: [],
        AutonomyRun: [], StructuralEvaluation: [],
    })

    result = public_activity(session)

    assert result["inbound_m2m_requests"] == 1
    assert result["inbound_m2m_requester_principals"] == ["TELEGRAPH"]
    assert result["m2m"]["requester_principals"] == ["TELEGRAPH"]


def test_public_activity_counts_only_processed_miner_responses_and_evidence():
    from app.domain.mandates import AcquisitionTask, AutonomyRun, Decision, Evidence, Mandate, PublicManualSpendReservation, StructuralEvaluation, TelegraphCall, Ticket

    now = datetime.now(timezone.utc)
    mandate = SimpleNamespace(mandate_id="m1", actor_id="human", origin="MANUAL", status="TICKETED")
    processed = SimpleNamespace(
        mandate_id="m1", acquisition_id="a1", telegraph_call_id="c1", status="SUCCEEDED",
        miner_id="miner-1", miner_name="Miner One", intent="CRYPTO_PRICE", signal_hash="0xsignal",
        duration_ms=120, cost_usd=Decimal("0.010000"), created_at=now,
    )
    transport_only = SimpleNamespace(
        mandate_id="m1", acquisition_id="a2", telegraph_call_id="c2", status="SUCCEEDED",
        miner_id=None, miner_name=None, intent="GAS_PRICE", signal_hash=None,
        duration_ms=80, cost_usd=Decimal("0.010000"), created_at=now,
    )
    evidence = SimpleNamespace(telegraph_call_id="c1", acquisition_id="a1")
    reservation = SimpleNamespace(mandate_id="m1", status="SETTLED", actual_spend_usdc=Decimal("0.010000"))
    session = Session({
        Mandate: [mandate], AcquisitionTask: [], TelegraphCall: [processed, transport_only],
        Evidence: [evidence], Decision: [], Ticket: [], AutonomyRun: [], StructuralEvaluation: [],
        PublicManualSpendReservation: [reservation],
    })

    result = public_activity(session)

    assert result["processed_responses"] == 1
    assert result["responses_with_evidence"] == 1
    assert result["unique_miners_processed"] == ["miner-1"]
    assert result["responses_by_intent"] == {"CRYPTO_PRICE": 1}
    assert result["actual_spend_usdc"] == "0.010000"
    assert result["latest_miner_response"]["economic_state"] == "PAYMENT_CONFIRMED"
    assert result["manual"]["processed_responses"] == 1


def test_public_activity_separates_demand_origin_from_fixture_responses():
    from app.domain.mandates import AcquisitionTask, AutonomyPolicy, AutonomyRun, Decision, Evidence, Mandate, StructuralEvaluation, TelegraphCall, Ticket

    manual = SimpleNamespace(mandate_id="m1", actor_id="human", origin="MANUAL", status="TICKETED", autonomy_policy_id=None)
    m2m = SimpleNamespace(mandate_id="m2m-1", actor_id="agent", origin="M2M", status="TICKETED", autonomy_policy_id=None)
    user = SimpleNamespace(mandate_id="user-1", actor_id="owner", origin="USER", status="TICKETED", autonomy_policy_id=None)
    fixture_mandate = SimpleNamespace(mandate_id="a1", actor_id="internal", origin="AUTONOMOUS", status="TICKETED", autonomy_policy_id="p1")
    manual_call = SimpleNamespace(mandate_id="m1", acquisition_id="a1", telegraph_call_id="c1", status="SUCCEEDED", miner_id="miner-1", signal_hash="0x1", intent="CRYPTO_PRICE", cost_usd=Decimal("0.010000"), duration_ms=10)
    m2m_call = SimpleNamespace(mandate_id="m2m-1", acquisition_id="a2", telegraph_call_id="c2", status="SUCCEEDED", miner_id="miner-2", signal_hash="0x2", intent="CRYPTO_PRICE", cost_usd=Decimal("0.010000"), duration_ms=10)
    user_call = SimpleNamespace(mandate_id="user-1", acquisition_id="a3", telegraph_call_id="c3", status="SUCCEEDED", miner_id="miner-3", signal_hash="0x3", intent="CRYPTO_PRICE", cost_usd=Decimal("0.010000"), duration_ms=10)
    fixture_call = SimpleNamespace(mandate_id="a1", acquisition_id="a2", telegraph_call_id="c2", status="SUCCEEDED", miner_id="miner-2", signal_hash="0x2", intent="CRYPTO_PRICE", cost_usd=Decimal("0.010000"), duration_ms=10)
    fixture_policy = SimpleNamespace(policy_id="p1", name="G10 Live Autonomous Telegraph Fixture")
    session = Session({
        Mandate: [manual, m2m, user, fixture_mandate],
        AutonomyPolicy: [fixture_policy],
        TelegraphCall: [manual_call, m2m_call, user_call, fixture_call],
        AcquisitionTask: [], Evidence: [], Decision: [], Ticket: [], AutonomyRun: [], StructuralEvaluation: [],
    })

    result = public_activity(session)

    assert result["demand_origin"] == {
        "total": 4,
        "external_user_driven": 3,
        "manual": 1,
        "m2m_inbound": 1,
        "user": 1,
        "fixture_canary": 1,
        "unattributed_legacy": 0,
    }
    assert result["manual"]["workflows_started"] == 1
    assert result["m2m"]["workflows_started"] == 1
    assert result["user"]["workflows_started"] == 1
    assert result["autonomous"]["workflows_started"] == 1


def test_public_execution_history_is_bounded_allowlisted_and_uses_persisted_evidence_hash():
    from app.domain.mandates import AcquisitionTask, AutonomyPolicy, AutonomyRun, Decision, Evidence, InboundX402Payment, Mandate, StructuralEvaluation, TelegraphCall, Ticket

    now = datetime.now(timezone.utc)
    m2m = SimpleNamespace(
        mandate_id="m2m-1", actor_id="x402-public", origin="M2M", status="TICKETED",
        agent_id="agent-17", client_id="PUBLIC_CLIENT", autonomy_policy_id=None,
    )
    private_user = SimpleNamespace(
        mandate_id="user-1", actor_id="user-owner", origin="USER", status="TICKETED",
        agent_id=None, client_id=None, autonomy_policy_id=None,
    )
    manual = SimpleNamespace(
        mandate_id="manual-1", actor_id="human", origin="MANUAL", status="RECEIVED",
        agent_id=None, client_id=None, autonomy_policy_id=None,
    )
    query = "BTC USD " + ("request " * 40)
    task = SimpleNamespace(
        mandate_id="m2m-1", acquisition_id="acq-1", query=query,
        requested_intent="CRYPTO_PRICE", status="SUCCEEDED", started_at=now, completed_at=now,
    )
    private_task = SimpleNamespace(
        mandate_id="user-1", acquisition_id="private-acq", query="private user question",
        requested_intent="RESEARCH_QUERY", status="SUCCEEDED", started_at=now, completed_at=now,
    )
    call = SimpleNamespace(
        mandate_id="m2m-1", acquisition_id="acq-1", telegraph_call_id="call-1",
        status="SUCCEEDED", miner_id="miner-1", miner_name="Miner One", intent="CRYPTO_PRICE",
        signal_hash="0xsignal", created_at=now, completed_at=now, cost_usd=Decimal("0.010000"),
        duration_ms=20, raw_response={"private_provider_field": "do-not-project"},
    )
    evidence = SimpleNamespace(
        mandate_id="m2m-1", acquisition_id="acq-1", telegraph_call_id="call-1",
        evidence_id="evidence-1", admissibility="ADMITTED", content_hash="0x" + "a" * 64,
        normalized_payload={"private_payload_field": "do-not-project"}, created_at=now,
    )
    private_evidence = SimpleNamespace(
        mandate_id="user-1", acquisition_id="private-acq", telegraph_call_id=None,
        evidence_id="private-evidence", admissibility="ADMITTED", content_hash="private-hash",
        normalized_payload={"private": True}, created_at=now,
    )
    cross_mandate_evidence = SimpleNamespace(
        mandate_id="manual-1", acquisition_id="acq-1", telegraph_call_id="call-1",
        evidence_id="cross-evidence", admissibility="ADMITTED", content_hash="wrong-mandate-hash",
        normalized_payload={"private": True}, created_at=now + timedelta(seconds=1),
    )
    decision = SimpleNamespace(mandate_id="m2m-1", decision_id="decision-1", state="PERMIT", created_at=now)
    payment = SimpleNamespace(
        mandate_id="m2m-1", payment_id="payment-1", payment_status="SETTLED",
        amount_usdc=Decimal("0.010000"), settled_at=now, created_at=now,
        payer_wallet_address="private-wallet", result_capability_hash="private-capability-hash",
    )
    session = Session({
        Mandate: [m2m, private_user, manual], AcquisitionTask: [task, private_task],
        TelegraphCall: [call], Evidence: [evidence, private_evidence, cross_mandate_evidence], Decision: [decision],
        InboundX402Payment: [payment], Ticket: [], AutonomyRun: [], StructuralEvaluation: [],
        AutonomyPolicy: [],
    })

    result = public_activity(session)
    history = result["execution_history"]

    assert len(history) == 1
    row = history[0]
    assert row == {
        "time": now.isoformat(),
        "origin": "M2M",
        "client": "agent-17",
        "intent": "CRYPTO_PRICE",
        "query": query[:240],
        "payment_amount_usdc": "0.010000",
        "acquisition_status": "SUCCEEDED",
        "evidence_status": "ADMITTED",
        "evidence_sha": "0x" + "a" * 64,
        "decision": "PERMIT",
        "delivery_status": "UNKNOWN",
    }
    assert "private user question" not in str(history)
    assert "private_payload_field" not in str(history)
    assert "private_provider_field" not in str(history)
    assert "private-wallet" not in str(history)
    assert "private-capability-hash" not in str(history)
    assert "wrong-mandate-hash" not in str(history)
    assert all(row["origin"] != "USER" for row in history)


def test_user_origin_detail_requires_owner_authorization():
    import pytest
    from fastapi import HTTPException
    from starlette.requests import Request

    from app.domain.mandates import Mandate
    from app.users.auth import protect_user_artifact

    user_mandate = SimpleNamespace(mandate_id="user-1", actor_id="owner-1", origin="USER")

    class OwnerSession(Session):
        def get(self, model, key):
            return user_mandate if model is Mandate and key == "user-1" else None

    path = "/v1/mandates/user-1/evidence"
    request = Request({
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
        "path_params": {"mandate_id": "user-1"},
    })

    with pytest.raises(HTTPException) as error:
        protect_user_artifact(request, OwnerSession({}))

    assert error.value.status_code == 401
    assert error.value.detail == "SESSION_REQUIRED"


def test_competition_budget_profile_reports_authorized_g12_cap(monkeypatch):
    from app.competition import competition_budget_profile

    monkeypatch.setenv("COMPETITION_MAX_WORKFLOW_USDC", "0.500000")
    result = competition_budget_profile()

    assert result["configured_max_usdc_per_workflow"] == "0.500000"
    assert result["effective_max_usdc_per_workflow"] == "0.050000"
    assert result["g12_hard_cap_applied"] is True


def test_ticket_summary_never_returns_mandate_text_or_raw_provider_payload():
    from app.domain.mandates import AcquisitionTask, Decision, Evidence, Mandate, StructuralEvaluation, TelegraphCall, Ticket

    now = datetime.now(timezone.utc)
    ticket = SimpleNamespace(ticket_id="t1", mandate_id="m1", schema_version="prama.ticket.v0", ticket_hash="0x" + "a" * 64, anchor_status="LOCAL_ONLY", created_at=now)
    mandate = SimpleNamespace(mandate_id="m1", mandate_type="CRYPTO_PRICE", origin="MANUAL", status="TICKETED", text="private user question", created_at=now)
    task = SimpleNamespace(acquisition_id="a1", status="SUCCEEDED", ordinal=0)
    call = SimpleNamespace(acquisition_id="a1", mandate_id="m1", intent="CRYPTO_PRICE", miner_name="public-miner", cost_usd=Decimal("0.001"), duration_ms=120, created_at=now)
    evidence = SimpleNamespace(evidence_id="e1", mandate_id="m1", admissibility="ADMITTED", provenance_status="VERIFIED", source_intent="CRYPTO_PRICE", content_hash="0x" + "b" * 64, limitation_codes=[] ,created_at=now)
    evaluation = SimpleNamespace(mandate_id="m1", structural_state="COMPLETE", limitation_codes=[], contradiction_codes=[], created_at=now)
    decision = SimpleNamespace(mandate_id="m1", state="PERMIT", reason_codes=["ALL_REQUIRED_EVIDENCE_ADMITTED"], created_at=now)

    class TicketSession(Session):
        def get(self, model, key):
            if model is Ticket and key == "t1":
                return ticket
            if model is Mandate and key == "m1":
                return mandate
            return None

    session = TicketSession({
        Ticket: [ticket], Mandate: [mandate], AcquisitionTask: [task], TelegraphCall: [call], Evidence: [evidence],
        StructuralEvaluation: [evaluation], Decision: [decision],
    })
    request = SimpleNamespace(base_url="https://example.test/")

    result = public_ticket_summary(session, "t1", request)

    assert result["workflow"]["summary"] == "Evidence-bound CRYPTO_PRICE workflow"
    assert "text" not in result["workflow"]
    assert "private user question" not in str(result)
    assert "raw_response" not in str(result)
    assert result["ticket"]["ticket_hash"] == ticket.ticket_hash
