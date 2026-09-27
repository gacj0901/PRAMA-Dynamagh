from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


class Query:
    """Small query double; read-model code still applies defensive filters."""

    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def filter_by(self, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def count(self):
        return len(self.rows)

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class Session:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return Query(self.rows.get(model, []))

    def get(self, model, key):
        for row in self.rows.get(model, []):
            if getattr(row, "mandate_id", None) == key or getattr(row, "ticket_id", None) == key:
                return row
        return None


def _mandate(mandate_id, *, origin="M2M", visibility="PUBLIC", **extra):
    values = dict(
        mandate_id=mandate_id,
        actor_id="agent",
        origin=origin,
        visibility=visibility,
        status="TICKETED",
        campaign_id=None,
        case_id=None,
        purpose=None,
        autonomy_policy_id=None,
        agent_id="agent-label",
        client_id="client-label",
        agent_identity_id=None,
    )
    values.update(extra)
    return SimpleNamespace(**values)


def test_internal_campaign_fields_are_durable_model_columns():
    from app.domain.mandates import Mandate

    columns = Mandate.__table__.c
    assert {"visibility", "campaign_id", "case_id", "purpose"}.issubset(columns.keys())
    assert columns.visibility.nullable is False
    assert str(columns.visibility.server_default.arg).strip("'") == "PUBLIC"
    assert columns.campaign_id.nullable is True
    assert columns.case_id.nullable is True
    assert columns.purpose.nullable is True


def test_either_internal_marker_is_excluded_but_legacy_public_rows_remain_visible():
    from app.read_visibility import is_internal_only

    assert is_internal_only(_mandate("by-origin", origin="INTERNAL_VALIDATION"))
    assert is_internal_only(_mandate("by-visibility", visibility="INTERNAL_ONLY"))
    assert not is_internal_only(_mandate("legacy", visibility=None))
    assert not is_internal_only(_mandate("public"))


def test_operator_mandate_inventory_and_detail_routes_hide_internal_rows():
    from app.api import mandates as routes
    from app.domain.mandates import Mandate

    internal = _mandate("campaign-1", origin="INTERNAL_VALIDATION", visibility="INTERNAL_ONLY")
    public = _mandate("public-1", origin="MANUAL")
    session = Session({Mandate: [internal, public]})

    assert routes.list_mandates(session) == [public]
    for handler, kwargs in (
        (routes.get_mandate, {}),
        (routes.timeline, {}),
        (routes.acquisitions, {}),
        (routes.evidence, {}),
        (routes.evaluation, {}),
        (routes.decision, {}),
        (routes.replay, {}),
        (routes.ticket, {}),
    ):
        with pytest.raises(HTTPException) as exc:
            handler("campaign-1", session)
        assert exc.value.status_code == 404


def test_public_activity_excludes_internal_rows_from_all_read_model_totals():
    from app.api.public_surfaces import public_activity
    from app.domain.mandates import (
        AcquisitionTask, AutonomyRun, Decision, Evidence, Mandate,
        PublicManualSpendReservation, StructuralEvaluation, TelegraphCall,
        Ticket, UsageEvent,
    )

    internal = _mandate("campaign-1", origin="INTERNAL_VALIDATION", visibility="INTERNAL_ONLY")
    disguised_m2m = _mandate("campaign-2", origin="M2M", visibility="INTERNAL_ONLY")
    now = datetime.now(timezone.utc)
    calls = [SimpleNamespace(
        mandate_id=mandate.mandate_id, acquisition_id=f"acq-{mandate.mandate_id}",
        telegraph_call_id=f"call-{mandate.mandate_id}", status="SUCCEEDED",
        miner_id="miner-secret", miner_name="internal miner", signal_hash="0xsignal",
        intent="FINANCIAL_DATA", duration_ms=10, cost_usd=Decimal("0.01"), created_at=now,
    ) for mandate in (internal, disguised_m2m)]
    tasks = [SimpleNamespace(mandate_id=item.mandate_id, acquisition_id=f"acq-{item.mandate_id}",
                             status="SUCCEEDED", failure_code=None) for item in (internal, disguised_m2m)]
    evidences = [SimpleNamespace(mandate_id=item.mandate_id, acquisition_id=f"acq-{item.mandate_id}",
                                 telegraph_call_id=f"call-{item.mandate_id}", evidence_id=f"ev-{item.mandate_id}")
                 for item in (internal, disguised_m2m)]
    session = Session({
        Mandate: [internal, disguised_m2m], TelegraphCall: calls, AcquisitionTask: tasks,
        Evidence: evidences, Decision: [], Ticket: [], AutonomyRun: [],
        StructuralEvaluation: [], PublicManualSpendReservation: [], UsageEvent: [],
    })

    result = public_activity(session)

    assert result["workflows_started"] == 0
    assert result["telegraph_calls"] == 0
    assert result["processed_responses"] == 0
    assert result["responses_by_intent"] == {}
    assert result["evidence_created"] == 0
    assert result["demand_origin"]["total"] == 0
    assert result["demand_origin"]["unattributed_legacy"] == 0
    assert result["execution_history"] == []
    assert result["operational_ledger"]["mandates"]["total"] == 0


def test_public_adoption_metrics_exclude_internal_origin_and_visibility():
    from app.api.adoption import adoption_snapshot
    from app.domain.mandates import (
        AcquisitionTask, AgentIdentity, Decision, Evidence, InboundX402Payment,
        Mandate, Ticket, UsageEvent,
    )

    public = _mandate("public-m2m", origin="M2M", agent_identity_id="id-public")
    internal_visibility = _mandate("campaign-m2m", origin="M2M", visibility="INTERNAL_ONLY",
                                   agent_identity_id="id-internal")
    internal_origin = _mandate("campaign-origin", origin="INTERNAL_VALIDATION",
                               visibility="PUBLIC", agent_identity_id="id-internal-origin")
    mandates = [public, internal_visibility, internal_origin]
    tasks = [SimpleNamespace(mandate_id=item.mandate_id, acquisition_id=f"acq-{item.mandate_id}",
                             status="SUCCEEDED") for item in mandates]
    payments = [SimpleNamespace(mandate_id=item.mandate_id, payment_status="SETTLED", network="eip155:84532",
                                payer_wallet_address=f"wallet-{item.mandate_id}", amount_usdc=Decimal("0.01"))
                for item in mandates]
    evidences = [SimpleNamespace(mandate_id=item.mandate_id, acquisition_id=f"acq-{item.mandate_id}",
                                 evidence_id=f"ev-{item.mandate_id}", admissibility="ADMITTED",
                                 provenance_status="VERIFIED", content_hash="not-proof") for item in mandates]
    events = [SimpleNamespace(mandate_id=item.mandate_id, event_type="M2M_CONSUMER_RESULT_DELIVERED",
                              metadata_={"delivery_surface": "x402-public-result",
                                         "delivery_scope": "SERVER_DELIVERY_CONFIRMED",
                                         "evidence_ids": [f"ev-{item.mandate_id}"],
                                         "acquisition_ids": [f"acq-{item.mandate_id}"]}) for item in mandates]
    session = Session({
        Mandate: mandates, AcquisitionTask: tasks, InboundX402Payment: payments,
        Evidence: evidences, UsageEvent: events,
        AgentIdentity: [SimpleNamespace(agent_id=f"id-{kind}") for kind in ("public", "internal", "internal-origin")],
        Decision: [], Ticket: [],
    })

    result = adoption_snapshot(session)

    assert result["metrics"] == {
        "external_m2m_requests": 1,
        "settled_m2m_requests": 1,
        "unique_paying_wallets": 1,
        "declared_client_labels": 1,
        "registered_m2m_agent_identities": 1,
        "successful_acquisitions": 1,
        "admitted_evidence": 1,
        "consumer_results_delivered": 1,
    }


def test_public_ticket_share_and_scoped_m2m_details_hide_internal_mandates():
    from app.api.m2m import _get_m2m_mandate
    from app.api.public_surfaces import public_ticket_summary
    from app.domain.mandates import Mandate, Ticket

    internal = _mandate("campaign-1", origin="M2M", visibility="INTERNAL_ONLY", m2m_context_id="ctx")
    ticket = SimpleNamespace(ticket_id="ticket-1", mandate_id="campaign-1")
    session = Session({Mandate: [internal], Ticket: [ticket]})
    with pytest.raises(HTTPException) as scoped:
        _get_m2m_mandate(session, "campaign-1", "ctx")
    assert scoped.value.status_code == 404
    with pytest.raises(HTTPException) as shared:
        public_ticket_summary(session, "ticket-1", SimpleNamespace(base_url="https://service.test/"))
    assert shared.value.status_code == 404


def test_user_history_and_detail_hide_internal_mandates(monkeypatch):
    from app.api import users as routes
    from app.domain.mandates import Mandate
    from app.users.models import UserMandate

    internal = _mandate("campaign-user", origin="USER", visibility="INTERNAL_ONLY")
    public = _mandate("public-user", origin="USER")
    links = [
        SimpleNamespace(mandate_id="campaign-user", user_id="user-1"),
        SimpleNamespace(mandate_id="public-user", user_id="user-1"),
    ]
    session = Session({Mandate: [internal, public], UserMandate: links})
    monkeypatch.setattr(routes, "mandate_json", lambda _session, mandate: {"mandate_id": mandate.mandate_id})
    response = SimpleNamespace(headers={})
    user = SimpleNamespace(user_id="user-1")

    assert routes.history(response, user, session) == [{"mandate_id": "public-user"}]
    with pytest.raises(HTTPException) as detail:
        routes.detail("campaign-user", response, user, session)
    assert detail.value.status_code == 404


def test_no_live_event_stream_is_registered_for_frontend_projection():
    from app.main import app

    assert not any(
        type(route).__name__ == "APIWebSocketRoute"
        or "text/event-stream" in str(
            getattr(getattr(route, "response_class", None), "media_type", "")
        ).lower()
        for route in app.routes
    )


def test_ticket_verification_and_anchor_reads_hide_internal_records(monkeypatch):
    from app import main
    from app.domain.mandates import Mandate, Ticket
    from app.persistence import database

    internal = _mandate("campaign-1", origin="INTERNAL_VALIDATION", visibility="INTERNAL_ONLY")
    ticket = SimpleNamespace(ticket_id="ticket-1", mandate_id="campaign-1")
    session = Session({Mandate: [internal], Ticket: [ticket]})

    session.close = lambda: None
    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    with pytest.raises(HTTPException) as anchor:
        main.get_ticket_anchor("ticket-1")
    verification = main.verify_ticket("ticket-1")
    assert anchor.value.status_code == 404
    assert verification == {"status": "INVALID", "failure_codes": ["TICKET_MISSING"]}


def test_campaign_adds_no_public_endpoint_or_paid_endpoint():
    from app.main import app

    paid_ask_routes = [route for route in app.routes
                       if getattr(route, "path", None) == "/v1/public/ask"
                       and "POST" in getattr(route, "methods", set())]
    assert len(paid_ask_routes) == 1
    assert not any("internal-validation" in str(getattr(route, "path", "")).lower()
                   for route in app.routes)
