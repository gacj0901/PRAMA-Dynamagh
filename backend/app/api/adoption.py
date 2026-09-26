"""Aggregate persisted M2M activity, never a payer or consumer directory."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.consumer_result import DELIVERY_EVENT
from app.domain.mandates import (Mandate, AcquisitionTask, Evidence, InboundX402Payment,
                                 UsageEvent, Decision, Ticket, AgentIdentity)
from app.persistence.database import get_session

router = APIRouter(tags=["adoption"])
PROOF_HASH = "0xed49ace56b0e3742b6cb4c1c19955ed77deff9075dd89bc4937954a1dec9d74f"


def adoption_snapshot(session):
    mids = session.query(Mandate.mandate_id).filter(Mandate.origin == "M2M")
    tasks = session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id.in_(mids))
    payments = session.query(InboundX402Payment).filter(
        InboundX402Payment.mandate_id.in_(mids), InboundX402Payment.payment_status == "SETTLED")
    admitted = session.query(Evidence).join(AcquisitionTask,
        (Evidence.acquisition_id == AcquisitionTask.acquisition_id) &
        (Evidence.mandate_id == AcquisitionTask.mandate_id)).filter(
        Evidence.mandate_id.in_(mids), Evidence.admissibility == "ADMITTED", Evidence.provenance_status == "VERIFIED")
    events = session.query(UsageEvent).filter(UsageEvent.mandate_id.in_(mids), UsageEvent.event_type == DELIVERY_EVENT).all()
    # Deduplicate operations, not GETs. Require persisted evidence/task lineage.
    delivered = set()
    delivered_evidence = set()
    eligible = {row.evidence_id: (row.mandate_id, row.acquisition_id) for row in admitted.all()}
    for event in events:
        metadata = event.metadata_ or {}
        if metadata.get("delivery_surface") != "x402-public-result" or metadata.get("delivery_scope") != "SERVER_DELIVERY_CONFIRMED":
            continue
        for eid in metadata.get("evidence_ids", []):
            lineage = eligible.get(eid)
            if lineage and lineage[0] == event.mandate_id and lineage[1] in metadata.get("acquisition_ids", []):
                delivered.add(event.mandate_id)
                delivered_evidence.add(eid)
    metrics = {
        "external_m2m_requests": mids.count(),
        "settled_m2m_requests": payments.with_entities(InboundX402Payment.mandate_id).distinct().count(),
        "unique_paying_wallets": payments.with_entities(InboundX402Payment.network,
            func.lower(InboundX402Payment.payer_wallet_address)).distinct().count(),
        "declared_client_labels": session.query(Mandate.agent_id).filter(Mandate.origin == "M2M",
            Mandate.agent_id.isnot(None), Mandate.agent_id != "").distinct().count(),
        "registered_m2m_agent_identities": session.query(AgentIdentity.agent_id).join(Mandate,
            Mandate.agent_identity_id == AgentIdentity.agent_id).filter(Mandate.origin == "M2M").distinct().count(),
        "successful_acquisitions": tasks.filter(AcquisitionTask.status == "SUCCEEDED").count(),
        "admitted_evidence": admitted.count(), "consumer_fulfilled": len(delivered),
    }
    proof = {"client": "KIMI_EXTERNAL", "intent": "WEATHER_FORECAST", "payment_usdc": "0.01",
             "acquisition": "SUCCEEDED", "evidence": "ADMITTED", "provenance": "VERIFIED",
             "decision": "PERMIT", "consumer_result": "DELIVERED", "evidence_content_hash": PROOF_HASH,
             "verification": "OPERATOR_ATTESTED", "source": "Operator-supplied certified execution; not added to metrics."}
    for evidence in admitted.filter(Evidence.content_hash == PROOF_HASH).all():
        mandate = session.get(Mandate, evidence.mandate_id)
        task = session.get(AcquisitionTask, evidence.acquisition_id)
        decision = session.query(Decision).filter_by(mandate_id=mandate.mandate_id).order_by(Decision.created_at.desc()).first()
        paid = payments.filter(InboundX402Payment.mandate_id == mandate.mandate_id,
                               InboundX402Payment.amount_usdc == Decimal("0.01")).first()
        if (mandate.agent_id == "KIMI_EXTERNAL" and task.requested_intent == "WEATHER_FORECAST"
                and task.status == "SUCCEEDED" and evidence.evidence_id in delivered_evidence and paid
                and decision and decision.state == "PERMIT"
                and session.query(Ticket).filter_by(mandate_id=mandate.mandate_id, decision_id=decision.decision_id).first()):
            proof["verification"] = "PERSISTED_LINEAGE_VERIFIED"
            proof["source"] = "Matched persisted mandate, payment, acquisition, admitted evidence, decision, ticket and delivery event."
    return {"schema_version": "prama-adoption-v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics, "scope": "Persisted M2M records; settled counts reflect application records, not an onchain reconciliation.",
            "metric_definitions": {"consumer_fulfilled": "Distinct mandates with at least one evidenced server content delivery; not necessarily all acquisitions or semantic correctness.",
                                   "declared_client_labels": "Distinct nonempty declared agent_id values; not verified independent agents.",
                                   "unique_paying_wallets": "Distinct normalized (network, payer) pairs on recorded settled payments.",
                                   "registered_m2m_agent_identities": "Distinct persistent identities referenced by M2M mandates; not verified independent agents."},
            "verified_execution": proof, "bazaar_metadata_declared": True, "bazaar_indexing_confirmed": False}


@router.get("/v1/public/adoption")
def adoption(response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "public, max-age=30"
    return adoption_snapshot(session)
