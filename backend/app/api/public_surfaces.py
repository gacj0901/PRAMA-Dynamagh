"""Small, read-only public surfaces for real Track 3 workflows.

These endpoints deliberately expose aggregates and identifiers only.  They do
not return mandate text, provider payloads, signer material, or any mutation
capability.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AcquisitionTask,
    AutonomyRun,
    Decision,
    Evidence,
    Mandate,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
)
from app.competition import competition_budget_profile
from app.persistence.database import get_session


router = APIRouter(tags=["public-read-surfaces"])
PUBLIC_ORIGINS = ("MANUAL", "M2M")


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Decimal | None) -> str:
    return f"{Decimal(value or 0):.6f}"


def _public_mandates(session: Session) -> list[Mandate]:
    rows = (
        session.query(Mandate)
        .filter(Mandate.origin.in_(PUBLIC_ORIGINS))
        .order_by(Mandate.created_at.asc(), Mandate.mandate_id.asc())
        .all()
    )
    # Keep the explicit origin boundary even when a non-standard Session
    # implementation is used by tooling or read-only diagnostics.
    return [item for item in rows if item.origin in PUBLIC_ORIGINS]


def public_activity(session: Session) -> dict[str, Any]:
    """Build bounded activity aggregates from public-origin records only.

    The database does not persist an independent TEST/SHADOW/INTERNAL
    environment label for every historical row.  The response therefore
    states the exact origin-based scope instead of guessing those categories.
    """

    mandates = _public_mandates(session)
    mandate_ids = [item.mandate_id for item in mandates]
    if not mandate_ids:
        return {
            "budget_profile": competition_budget_profile(),
            "scope": {
                "included_origins": list(PUBLIC_ORIGINS),
                "excluded_origins": ["AUTONOMOUS", "INTERNAL", "SHADOW"],
                "test_classification": "NOT_PERSISTED_SEPARATELY",
            },
            "real_users": 0,
            "workflows_started": 0,
            "workflows_completed": 0,
            "returning_users": 0,
            "telegraph_calls": 0,
            "telegraph_successful_calls": 0,
            "real_miners_used": [],
            "intents_used": [],
            "multi_intent_workflows": 0,
            "evidence_created": 0,
            "decisions_emitted": 0,
            "tickets_emitted": 0,
            "autonomous_runs": session.query(AutonomyRun).count(),
            "completion_rate": 0.0,
            "average_calls_per_workflow": 0.0,
            "average_evidence_per_workflow": 0.0,
            "average_latency_ms": None,
            "public_spend_usdc": "0.000000",
        }

    tasks = session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id.in_(mandate_ids)).all()
    calls = session.query(TelegraphCall).filter(TelegraphCall.mandate_id.in_(mandate_ids)).all()
    evidence = session.query(Evidence).filter(Evidence.mandate_id.in_(mandate_ids)).all()
    decisions = session.query(Decision).filter(Decision.mandate_id.in_(mandate_ids)).all()
    tickets = session.query(Ticket).filter(Ticket.mandate_id.in_(mandate_ids)).all()

    actor_counts = Counter(item.actor_id for item in mandates)
    successful_calls = [item for item in calls if item.status == "SUCCEEDED"]
    calls_by_mandate = Counter(item.mandate_id for item in successful_calls)
    intents_by_mandate: dict[str, set[str]] = {}
    for item in successful_calls:
        if item.intent:
            intents_by_mandate.setdefault(item.mandate_id, set()).add(item.intent)
    durations = [item.duration_ms for item in successful_calls if item.duration_ms is not None]
    public_spend = sum((Decimal(item.cost_usd or 0) for item in successful_calls), Decimal("0"))

    return {
        "budget_profile": competition_budget_profile(),
        "scope": {
            "included_origins": list(PUBLIC_ORIGINS),
            "excluded_origins": ["AUTONOMOUS", "INTERNAL", "SHADOW"],
            "test_classification": "NOT_PERSISTED_SEPARATELY",
        },
        "real_users": len(actor_counts),
        "workflows_started": len(mandates),
        "workflows_completed": sum(item.status == "TICKETED" for item in mandates),
        "returning_users": sum(count > 1 for count in actor_counts.values()),
        "telegraph_calls": len(calls),
        "telegraph_successful_calls": len(successful_calls),
        "real_miners_used": sorted({str(item.miner_id) for item in successful_calls if item.miner_id}),
        "intents_used": sorted({str(item.intent) for item in successful_calls if item.intent}),
        "multi_intent_workflows": sum(len(intents) > 1 for intents in intents_by_mandate.values()),
        "evidence_created": len(evidence),
        "decisions_emitted": len(decisions),
        "tickets_emitted": len(tickets),
        "autonomous_runs": session.query(AutonomyRun).count(),
        "completion_rate": round(sum(item.status == "TICKETED" for item in mandates) / len(mandates), 6),
        "average_calls_per_workflow": round(len(successful_calls) / len(mandates), 6),
        "average_evidence_per_workflow": round(len(evidence) / len(mandates), 6),
        "average_latency_ms": round(sum(durations) / len(durations), 3) if durations else None,
        "public_spend_usdc": _money(public_spend),
    }


@router.get("/v1/public/activity")
def activity(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return aggregate activity from persisted public-origin workflows."""

    return public_activity(session)


def public_ticket_summary(session: Session, ticket_id: str, request: Request) -> dict[str, Any]:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="TICKET_MISSING")
    mandate = session.get(Mandate, ticket.mandate_id)
    if mandate is None:
        raise HTTPException(status_code=404, detail="MANDATE_MISSING")
    if mandate.origin not in PUBLIC_ORIGINS:
        raise HTTPException(status_code=404, detail="PUBLIC_TICKET_MISSING")

    tasks = (
        session.query(AcquisitionTask)
        .filter(AcquisitionTask.mandate_id == mandate.mandate_id)
        .order_by(AcquisitionTask.ordinal.asc(), AcquisitionTask.acquisition_id.asc())
        .all()
    )
    calls = (
        session.query(TelegraphCall)
        .filter(TelegraphCall.mandate_id == mandate.mandate_id)
        .order_by(TelegraphCall.created_at.asc(), TelegraphCall.telegraph_call_id.asc())
        .all()
    )
    evidence = (
        session.query(Evidence)
        .filter(Evidence.mandate_id == mandate.mandate_id)
        .order_by(Evidence.created_at.asc(), Evidence.evidence_id.asc())
        .all()
    )
    evaluation = (
        session.query(StructuralEvaluation)
        .filter(StructuralEvaluation.mandate_id == mandate.mandate_id)
        .order_by(StructuralEvaluation.created_at.desc())
        .first()
    )
    decision = (
        session.query(Decision)
        .filter(Decision.mandate_id == mandate.mandate_id)
        .order_by(Decision.created_at.desc())
        .first()
    )

    limitations = list(dict.fromkeys(
        (evaluation.limitation_codes if evaluation else [])
        + [code for item in evidence for code in (item.limitation_codes or [])]
    ))
    calls_by_acquisition = {item.acquisition_id: item for item in calls}
    # Relative public-proxy paths avoid leaking an internal API host when the
    # request arrived through the frontend gateway.
    verification_url = f"/api/v1/tickets/{ticket.ticket_id}/verify"
    replay_url = f"/api/v1/mandates/{mandate.mandate_id}/replay"

    return {
        "share_schema": "prama.ticket.share.v1",
        "workflow": {
            "mandate_id": mandate.mandate_id,
            "mandate_type": mandate.mandate_type,
            "origin": mandate.origin,
            "status": mandate.status,
            "summary": f"Evidence-bound {mandate.mandate_type} workflow",
            "created_at": _iso(mandate.created_at),
        },
        "acquisitions": [
            {
                "acquisition_id": task.acquisition_id,
                "status": task.status,
                "intent": calls_by_acquisition.get(task.acquisition_id).intent if calls_by_acquisition.get(task.acquisition_id) else None,
                "miner": calls_by_acquisition.get(task.acquisition_id).miner_name if calls_by_acquisition.get(task.acquisition_id) else None,
                "cost_usdc": _money(calls_by_acquisition.get(task.acquisition_id).cost_usd) if calls_by_acquisition.get(task.acquisition_id) else "0.000000",
                "duration_ms": calls_by_acquisition.get(task.acquisition_id).duration_ms if calls_by_acquisition.get(task.acquisition_id) else None,
            }
            for task in tasks
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "admissibility": item.admissibility,
                "provenance_status": item.provenance_status,
                "source_intent": item.source_intent,
                "content_hash": item.content_hash,
            }
            for item in evidence
        ],
        "evaluation": None if evaluation is None else {
            "structural_state": evaluation.structural_state,
            "limitations": evaluation.limitation_codes or [],
            "contradictions": evaluation.contradiction_codes or [],
        },
        "decision": None if decision is None else {
            "state": decision.state,
            "reason_codes": decision.reason_codes or [],
        },
        "ticket": {
            "ticket_id": ticket.ticket_id,
            "schema_version": ticket.schema_version,
            "ticket_hash": ticket.ticket_hash,
            "anchor_status": ticket.anchor_status,
            "created_at": _iso(ticket.created_at),
        },
        "limitations": limitations,
        "verification": {"status": "AVAILABLE", "url": verification_url},
        "replay": {"status": "AVAILABLE", "url": replay_url},
    }


@router.get("/v1/tickets/{ticket_id}/share")
def share_ticket(ticket_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return a safe, public, non-payload Ticket summary."""

    return public_ticket_summary(session, ticket_id, request)
