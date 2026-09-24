"""Local persisted proof: a settled miner result is not authority to act.

All payment/call data is fixture-only in an in-memory SQLite store. The test
uses the production CRYPTO_PRICE E1 evaluator, prama-gate-v0 mapping, Ticket
builder, and persisted-artifact replay/verification functions. It has no
acquisition adapter, network client, or payment facilitator.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "JSON"


from app.domain.mandates import (  # noqa: E402
    AcquisitionTask,
    CryptoPriceEvidence,
    Decision,
    Evidence,
    EvidenceRequirement,
    EvidenceRelation,
    EpistemicEvaluation,
    EpistemicTarget,
    Mandate,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
)
from app.epistemic.contracts import (  # noqa: E402
    build_crypto_price_evidence,
    build_crypto_price_target,
    build_evidence_requirement,
)
from app.epistemic.evaluator import (  # noqa: E402
    evaluate_crypto_price,
    persist_e1_evaluation,
    replay_crypto_price,
)
from app.pramagraph.evaluation import classify, decide, digest  # noqa: E402
from app.pramagraph.fanout import VERSION as FANOUT_VERSION, structural_state  # noqa: E402
from app.pramagraph.replay import replay as replay_mandate  # noqa: E402
from app.tickets.core import build as build_ticket, hash_core  # noqa: E402
from app.tickets.service import verify as verify_ticket  # noqa: E402
from app.persistence.database import Base  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
PROOF = json.loads((ROOT / "tests" / "fixtures" / "paid_output_not_authorization.json").read_text())
REQUEST = PROOF["request"]["text"]
INTENT = PROOF["request"]["intent"]
OBSERVED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
TABLES = (
    Mandate.__table__,
    AcquisitionTask.__table__,
    TelegraphCall.__table__,
    Evidence.__table__,
    EpistemicTarget.__table__,
    EvidenceRequirement.__table__,
    CryptoPriceEvidence.__table__,
    EvidenceRelation.__table__,
    EpistemicEvaluation.__table__,
    StructuralEvaluation.__table__,
    Decision.__table__,
    Ticket.__table__,
)


def _session():
    engine = create_engine("sqlite://")
    for table in TABLES:
        table.create(engine, checkfirst=True)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _persist_case(session, label):
    spec = PROOF["cases"][label]
    payment = dict(PROOF["payment"])
    response = {
        "result": {
            "asset": spec["observed_asset"],
            "price": "50000.00",
            "currency": "USD",
            "observed_at": OBSERVED_AT.isoformat(),
        },
        "warnings": list(spec["warnings"]),
        "payment": payment,
    }
    mandate = Mandate(
        mandate_id=spec["mandate_id"],
        actor_id="local-proof-fixture",
        text=REQUEST,
        mandate_type=INTENT,
        constraints={},
        max_budget_usdc=Decimal("0.010000"),
        status="DECIDED",
        origin="MANUAL",
    )
    task = AcquisitionTask(
        acquisition_id=spec["acquisition_id"],
        mandate_id=spec["mandate_id"],
        query=REQUEST,
        requested_intent=INTENT,
        required=True,
        status="SUCCEEDED",
        ordinal=0,
        target_subject="BTC",
        target_property="price",
        target_unit="USD",
        target_schema_version=INTENT,
        temporal_scope={"as_of": OBSERVED_AT.isoformat()},
    )
    call = TelegraphCall(
        telegraph_call_id=spec["telegraph_call_id"],
        mandate_id=spec["mandate_id"],
        acquisition_id=spec["acquisition_id"],
        causal_request_id=spec["mandate_id"],
        miner_id="fixture-miner-402",
        miner_name="Local proof fixture",
        intent=INTENT,
        signal_hash="0x" + "ab" * 32,
        cost_usd=Decimal(payment["amount_usdc"]),
        duration_ms=1,
        warnings=list(spec["warnings"]),
        raw_response=response,
        resource_provider="TELEGRAPH_FIXTURE",
        access_mechanism="TEST_FIXTURE",
        payment_rail="TEST_FIXTURE",
        status="SUCCEEDED",
    )

    # Exercise the production admission classifier with a persisted successful
    # response. Case B differs only in its returned Evidence condition.
    admissibility, limitations = classify(call, verified=True)
    normalized = {
        "intent": INTENT,
        "result": response["result"],
        "warnings": response["warnings"],
        "miner_id": call.miner_id,
        "signal_hash": call.signal_hash,
    }
    evidence = Evidence(
        evidence_id=spec["evidence_id"],
        mandate_id=spec["mandate_id"],
        acquisition_id=spec["acquisition_id"],
        telegraph_call_id=spec["telegraph_call_id"],
        evidence_type="TELEGRAPH_RESULT",
        source_kind="TELEGRAPH",
        source_intent=INTENT,
        source_miner_id=call.miner_id,
        source_signal_hash=call.signal_hash,
        normalized_payload=normalized,
        content_hash=digest(normalized),
        normalizer_version="telegraph-evidence-v0",
        provenance_status="VERIFIED",
        admissibility=admissibility,
        limitation_codes=limitations,
    )

    target = build_crypto_price_target(
        mandate_id=spec["mandate_id"],
        target_id=spec["target_id"],
        asset="BTC",
        quote_currency="USD",
        as_of=OBSERVED_AT,
    )
    requirement_types = (
        "asset_identity",
        "quote_currency",
        "price_value",
        "temporal_applicability",
    )
    requirements = [
        build_evidence_requirement(
            target_id=spec["target_id"],
            requirement_id=spec["requirement_ids"][index],
            requirement_type=kind,
            parameters={"max_age_seconds": 60} if kind == "temporal_applicability" else {},
        )
        for index, kind in enumerate(requirement_types)
    ]
    typed = build_crypto_price_evidence(
        evidence_id=spec["evidence_id"],
        crypto_price_evidence_id=spec["typed_evidence_id"],
        asset=spec["observed_asset"],
        quote_currency="USD",
        price_value="50000.00",
        observed_at=OBSERVED_AT,
    )

    session.add_all([mandate, task, call, evidence, target, *requirements, typed])
    session.flush()
    e1 = evaluate_crypto_price(
        target=target,
        requirements=requirements,
        evidence=[evidence],
        typed_evidence_by_id={evidence.evidence_id: typed},
        mandate_id=spec["mandate_id"],
    )
    persist_e1_evaluation(session, e1)

    state = structural_state([evidence], [task])
    decision_state, reasons = decide(state)
    structural = StructuralEvaluation(
        evaluation_id=spec["structural_evaluation_id"],
        mandate_id=spec["mandate_id"],
        evaluator="PRAMAGRAPH",
        evaluator_version=FANOUT_VERSION,
        evidence_set_hash=digest([evidence.content_hash]),
        admitted_evidence_ids=[evidence.evidence_id] if admissibility == "ADMITTED" else [],
        limited_evidence_ids=[evidence.evidence_id] if admissibility == "LIMITED" else [],
        rejected_evidence_ids=[],
        limitation_codes=limitations,
        contradiction_codes=[],
        structural_state=state,
        evaluation_payload={"acquisition_failures": [], "absence_imputed": False},
    )
    decision = Decision(
        decision_id=spec["decision_id"],
        mandate_id=spec["mandate_id"],
        evaluation_id=spec["structural_evaluation_id"],
        state=decision_state,
        policy_version="prama-gate-v0",
        evidence_set_hash=structural.evidence_set_hash,
        reason_codes=reasons,
        decision_payload={},
    )
    session.add_all([structural, decision])
    session.flush()

    ticket_body = build_ticket(mandate, decision, structural, [evidence], [call], [task])
    ticket = Ticket(
        ticket_id=spec["ticket_id"],
        mandate_id=spec["mandate_id"],
        decision_id=decision.decision_id,
        schema_version=ticket_body["schema_version"],
        canonical_payload=ticket_body,
        ticket_hash=hash_core(ticket_body),
        hash_algorithm="keccak256",
        anchor_status="LOCAL_ONLY",
    )
    session.add(ticket)
    session.commit()
    return spec, e1


def _replay_case(session, spec, original_e1, network_attempts):
    calls_before = session.query(TelegraphCall).count()
    tickets_before = session.query(Ticket).count()
    settlements_before = sum(
        call.raw_response.get("payment", {}).get("status") == "SETTLED"
        for call in session.query(TelegraphCall).all()
    )
    target = session.get(EpistemicTarget, spec["target_id"])
    requirements = (
        session.query(EvidenceRequirement)
        .filter_by(target_id=spec["target_id"])
        .order_by(EvidenceRequirement.requirement_type)
        .all()
    )
    evidence = session.query(Evidence).filter_by(mandate_id=spec["mandate_id"]).all()
    typed_rows = session.query(CryptoPriceEvidence).filter_by(evidence_id=spec["evidence_id"]).all()
    typed = {
        row.evidence_id: CryptoPriceEvidence(
            evidence_id=row.evidence_id,
            asset=row.asset,
            quote_currency=row.quote_currency,
            price_value=row.price_value,
            observed_at=row.observed_at.replace(tzinfo=timezone.utc)
            if row.observed_at.tzinfo is None
            else row.observed_at,
            schema_version=row.schema_version,
            canonical_hash=row.canonical_hash,
        )
        for row in typed_rows
    }
    replayed_e1 = replay_crypto_price(
        target=target,
        requirements=requirements,
        evidence=evidence,
        typed_evidence_by_id=typed,
        mandate_id=spec["mandate_id"],
    )
    gate_result = replay_mandate(session, spec["mandate_id"])
    ticket = session.get(Ticket, spec["ticket_id"])
    ticket_result = verify_ticket(session, ticket)
    settlements_after = sum(
        call.raw_response.get("payment", {}).get("status") == "SETTLED"
        for call in session.query(TelegraphCall).all()
    )
    assert session.query(TelegraphCall).count() == calls_before
    assert session.query(Ticket).count() == tickets_before
    assert replayed_e1.evaluation.canonical_hash == original_e1.evaluation.canonical_hash
    assert [row.canonical_hash for row in replayed_e1.relations] == [
        row.canonical_hash for row in original_e1.relations
    ]
    assert gate_result["matches"] is True
    assert ticket_result["status"] == "VALID"
    return {
        "e1_hash_match": True,
        "gate_match": gate_result["matches"],
        "ticket_status": ticket_result["status"],
        "network_calls": len(network_attempts),
        "new_settlements": settlements_after - settlements_before,
    }


def test_paid_miner_output_is_not_authorization_and_replays_persisted_artifacts(monkeypatch):
    import socket

    session = _session()
    try:
        artifacts = {
            label: _persist_case(session, label)
            for label in ("A", "B")
        }
        results = {}
        before_call_count = session.query(TelegraphCall).count()

        network_attempts = []

        def reject_network(*_args, **_kwargs):
            network_attempts.append("blocked")
            raise AssertionError("replay attempted network access")

        monkeypatch.setattr(socket.socket, "connect", reject_network)
        for label, (spec, e1) in artifacts.items():
            call = session.get(TelegraphCall, spec["telegraph_call_id"])
            evidence = session.get(Evidence, spec["evidence_id"])
            decision = session.get(Decision, spec["decision_id"])
            ticket = session.get(Ticket, spec["ticket_id"])
            results[label] = {
                "payment": call.raw_response["payment"]["status"],
                "request": (INTENT, session.get(AcquisitionTask, spec["acquisition_id"]).query),
                "evidence_id": evidence.evidence_id,
                "evidence_state": evidence.admissibility,
                "evaluation": e1.evaluation.structural_state,
                "relations": sorted({relation.relation_state for relation in e1.relations}),
                "decision": decision.state,
                "ticket_id": ticket.ticket_id,
                "replay_result": _replay_case(session, spec, e1, network_attempts),
            }

        assert results["A"]["payment"] == results["B"]["payment"] == "SETTLED"
        assert results["A"]["request"] == results["B"]["request"] == (INTENT, REQUEST)
        assert results["A"]["evidence_state"] == "ADMITTED"
        assert results["B"]["evidence_state"] == "LIMITED"
        assert results["A"]["evaluation"] == "COMPLETE"
        assert results["B"]["evaluation"] == "CONTRADICTED"
        assert "CONTRADICTS" in results["B"]["relations"]
        assert results["A"]["decision"] == "PERMIT"
        assert results["B"]["decision"] == "REVIEW"
        assert results["A"]["decision"] != results["B"]["decision"]
        assert session.query(TelegraphCall).count() == before_call_count == 2
        assert all(result["replay_result"]["new_settlements"] == 0 for result in results.values())
        assert all(result["replay_result"]["network_calls"] == 0 for result in results.values())
    finally:
        session.close()
