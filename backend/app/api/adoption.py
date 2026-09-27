"""Aggregate persisted M2M activity, never a payer or consumer directory."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.bazaar_observation import indexing_observation
from app.api.consumer_result import DELIVERY_EVENT
from app.domain.mandates import (Mandate, AcquisitionTask, Evidence, InboundX402Payment,
                                 UsageEvent, Decision, Ticket, AgentIdentity)
from app.persistence.database import get_session
from app.read_visibility import frontend_visibility_clause, is_internal_only

router = APIRouter(tags=["adoption"])
PROOF_HASH = "0xed49ace56b0e3742b6cb4c1c19955ed77deff9075dd89bc4937954a1dec9d74f"


def adoption_snapshot(session):
    visible_mandates = session.query(Mandate).filter(
        Mandate.origin == "M2M", frontend_visibility_clause(Mandate.visibility)
    ).all()
    visible_mandates = [
        mandate for mandate in visible_mandates
        if mandate.origin == "M2M" and not is_internal_only(mandate)
    ]
    mids = {mandate.mandate_id for mandate in visible_mandates}
    tasks = [task for task in session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id.in_(mids)).all()
             if task.mandate_id in mids]
    settled_payments = [payment for payment in session.query(InboundX402Payment).filter(
        InboundX402Payment.mandate_id.in_(mids), InboundX402Payment.payment_status == "SETTLED"
    ).all() if payment.mandate_id in mids and payment.payment_status == "SETTLED"]
    task_by_acquisition = {task.acquisition_id: task for task in tasks}
    admitted = [evidence for evidence in session.query(Evidence).filter(
        Evidence.mandate_id.in_(mids), Evidence.admissibility == "ADMITTED",
        Evidence.provenance_status == "VERIFIED",
    ).all() if evidence.mandate_id in mids
        and evidence.admissibility == "ADMITTED"
        and evidence.provenance_status == "VERIFIED"
        and evidence.acquisition_id in task_by_acquisition
        and task_by_acquisition[evidence.acquisition_id].mandate_id == evidence.mandate_id]
    events = [event for event in session.query(UsageEvent).filter(
        UsageEvent.mandate_id.in_(mids), UsageEvent.event_type == DELIVERY_EVENT
    ).all() if event.mandate_id in mids and event.event_type == DELIVERY_EVENT]
    # Deduplicate operations, not GETs. Require persisted evidence/task lineage.
    delivered = set()
    delivered_evidence = set()
    eligible = {row.evidence_id: (row.mandate_id, row.acquisition_id) for row in admitted}
    for event in events:
        metadata = event.metadata_ or {}
        if metadata.get("delivery_surface") != "x402-public-result" or metadata.get("delivery_scope") != "SERVER_DELIVERY_CONFIRMED":
            continue
        for eid in metadata.get("evidence_ids", []):
            lineage = eligible.get(eid)
            if lineage and lineage[0] == event.mandate_id and lineage[1] in metadata.get("acquisition_ids", []):
                delivered.add(event.mandate_id)
                delivered_evidence.add(eid)
    identity_ids = {mandate.agent_identity_id for mandate in visible_mandates if mandate.agent_identity_id}
    registered_identity_ids = {
        identity.agent_id for identity in session.query(AgentIdentity).filter(
            AgentIdentity.agent_id.in_(identity_ids)
        ).all() if identity.agent_id in identity_ids
    }
    metrics = {
        "external_m2m_requests": len(visible_mandates),
        "settled_m2m_requests": len({payment.mandate_id for payment in settled_payments}),
        "unique_paying_wallets": len({
            (payment.network, str(payment.payer_wallet_address).lower()) for payment in settled_payments
        }),
        "declared_client_labels": len({mandate.agent_id for mandate in visible_mandates
                                        if mandate.agent_id is not None and mandate.agent_id != ""}),
        "registered_m2m_agent_identities": len(registered_identity_ids),
        "successful_acquisitions": sum(task.status == "SUCCEEDED" for task in tasks),
        "admitted_evidence": len(admitted), "consumer_results_delivered": len(delivered),
    }
    proof = {"client": "KIMI_EXTERNAL", "intent": "WEATHER_FORECAST", "payment_usdc": "0.01",
             "acquisition": "SUCCEEDED", "evidence": "ADMITTED", "provenance": "VERIFIED",
             "decision": "PERMIT", "consumer_result": "DELIVERED", "evidence_content_hash": PROOF_HASH,
             "verification": "OPERATOR_ATTESTED", "source": "Operator-supplied certified execution; not added to metrics."}
    for evidence in admitted:
        if evidence.content_hash != PROOF_HASH:
            continue
        mandate = session.get(Mandate, evidence.mandate_id)
        task = session.get(AcquisitionTask, evidence.acquisition_id)
        decision = session.query(Decision).filter_by(mandate_id=mandate.mandate_id).order_by(Decision.created_at.desc()).first()
        paid = next((payment for payment in settled_payments
                     if payment.mandate_id == mandate.mandate_id
                     and payment.amount_usdc == Decimal("0.01")), None)
        if (mandate.agent_id == "KIMI_EXTERNAL" and task.requested_intent == "WEATHER_FORECAST"
                and task.status == "SUCCEEDED" and evidence.evidence_id in delivered_evidence and paid
                and decision and decision.state == "PERMIT"
                and session.query(Ticket).filter_by(mandate_id=mandate.mandate_id, decision_id=decision.decision_id).first()):
            proof["verification"] = "PERSISTED_LINEAGE_VERIFIED"
            proof["source"] = "Matched persisted mandate, payment, acquisition, admitted evidence, decision, ticket and delivery event."
    return {"schema_version": "prama-adoption-v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics, "scope": "Persisted M2M records; settled counts reflect application records, not an onchain reconciliation.",
            "metric_definitions": {"consumer_results_delivered": "Distinct mandates with at least one evidenced server content delivery; not necessarily all acquisitions or semantic correctness.",
                                   "declared_client_labels": "Distinct nonempty declared agent_id values; not verified independent agents.",
                                   "unique_paying_wallets": "Distinct normalized (network, payer) pairs on recorded settled payments.",
                                   "registered_m2m_agent_identities": "Distinct persistent identities referenced by M2M mandates; not verified independent agents."},
            "verified_execution": proof, "bazaar_metadata_declared": True, **indexing_observation(), "semantic_task_fulfillment": "NOT_INFERRED_FROM_DELIVERY"}


@router.get("/v1/public/adoption")
def adoption(response: Response, session: Session = Depends(get_session)):
    response.headers["Cache-Control"] = "public, max-age=30"
    return adoption_snapshot(session)
