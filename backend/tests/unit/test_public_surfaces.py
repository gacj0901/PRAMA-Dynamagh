from datetime import datetime, timezone
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
