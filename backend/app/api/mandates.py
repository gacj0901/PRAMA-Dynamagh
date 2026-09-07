from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domain.mandates import AcquisitionTask, AcquisitionStatus, Mandate, MandateStatus, MandateTransition, UsageEvent
from app.workers.tasks import execute_acquisition
from app.persistence.database import get_session
from app.public_safety import enforce_public_budget, enforce_public_rate_limit, reserve_public_manual_spend
from app.competition import competition_max_calls_per_workflow

router = APIRouter(prefix="/v1/mandates", tags=["mandates"])


class AcquisitionInput(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    requested_intent: str | None = Field(default=None, min_length=1, max_length=255)


class MandateCreate(BaseModel):
    actor_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=20_000)
    mandate_type: str = Field(default="GENERAL", min_length=1, max_length=100)
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_budget_usdc: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    deadline: datetime | None = None
    acquisitions: list[AcquisitionInput] = Field(default_factory=list, max_length=5)


class MandateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mandate_id: str
    actor_id: str
    text: str
    mandate_type: str
    constraints: dict[str, Any]
    max_budget_usdc: Decimal
    deadline: datetime | None
    status: str
    origin: str
    autonomy_policy_id: str | None
    autonomy_run_id: str | None
    created_at: datetime
    updated_at: datetime
    acquisitions: list[dict[str, Any]] = []


@router.get("", response_model=list[MandateRead])
def list_mandates(session: Session = Depends(get_session)) -> list[Mandate]:
    """Read-only inventory used by the operator interface.

    The endpoint intentionally returns only persisted Mandate fields.  Detailed
    artifacts remain available through the existing mandate-scoped endpoints.
    """
    return session.query(Mandate).filter(Mandate.origin != 'USER').order_by(Mandate.updated_at.desc()).all()


@router.post("", response_model=MandateRead, status_code=status.HTTP_202_ACCEPTED)
def create_mandate(payload: MandateCreate, request: Request, session: Session = Depends(get_session)) -> Mandate:
    """Accept one public manual workflow only after durable spend authorization."""
    enforce_public_rate_limit(request)
    enforce_public_budget(payload.max_budget_usdc)
    try:
        if len(payload.acquisitions) > competition_max_calls_per_workflow():
            raise HTTPException(status_code=422, detail="WORKFLOW_ACQUISITION_COUNT_EXCEEDED")
        mandate = Mandate(
            actor_id=payload.actor_id,
            text=payload.text,
            mandate_type=payload.mandate_type,
            constraints=payload.constraints,
            max_budget_usdc=payload.max_budget_usdc,
            deadline=payload.deadline,
            status=MandateStatus.RECEIVED.value,
            origin="MANUAL",
        )
        session.add(mandate)
        session.flush()
        reserve_public_manual_spend(session, mandate.mandate_id, mandate.max_budget_usdc)
        plan = payload.acquisitions or [AcquisitionInput(query=mandate.text)]
        tasks = [
            AcquisitionTask(
                mandate_id=mandate.mandate_id,
                query=item.query,
                requested_intent=item.requested_intent,
                required=True,
                status=AcquisitionStatus.QUEUED.value,
                ordinal=ordinal,
            )
            for ordinal, item in enumerate(plan)
        ]
        session.add_all(tasks)
        session.flush()  # Attribute queued events to materialized task identities.
        session.add_all([
            MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="mandate created"),
            UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_={}),
            *[UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_={}) for task in tasks],
        ])
        session.commit()
        session.refresh(mandate)
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE") from error
    # A broker outage retains the reservation instead of authorizing an
    # unaccounted retry.  The worker therefore remains fail-closed on spend.
    execute_acquisition.delay(mandate.mandate_id, tasks[0].acquisition_id)
    mandate.acquisitions = [{"acquisition_id": task.acquisition_id, "ordinal": task.ordinal, "query": task.query, "status": task.status} for task in tasks]
    return mandate


@router.get("/{mandate_id}", response_model=MandateRead)
def get_mandate(mandate_id: str, session: Session = Depends(get_session)) -> Mandate:
    mandate = session.get(Mandate, mandate_id)
    if mandate is None:
        raise HTTPException(status_code=404, detail="mandate not found")
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).all()
    mandate.acquisitions = [{"acquisition_id": t.acquisition_id, "status": t.status, "requested_intent": t.requested_intent, "attempt_count": t.attempt_count, "failure_code": t.failure_code} for t in tasks]
    return mandate


@router.get("/{mandate_id}/timeline")
def timeline(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return the persisted state and usage chronology without side effects."""
    mandate = session.get(Mandate, mandate_id)
    if mandate is None:
        raise HTTPException(status_code=404, detail="mandate not found")
    transitions = session.query(MandateTransition).filter_by(mandate_id=mandate_id).order_by(MandateTransition.created_at).all()
    events = session.query(UsageEvent).filter_by(mandate_id=mandate_id).order_by(UsageEvent.created_at).all()
    return {
        "mandate_id": mandate_id,
        "transitions": [
            {
                "transition_id": item.transition_id,
                "from_status": item.from_status,
                "to_status": item.to_status,
                "reason": item.reason,
                "created_at": item.created_at,
            }
            for item in transitions
        ],
        "events": [
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "acquisition_id": item.acquisition_id,
                "metadata": item.metadata_,
                "created_at": item.created_at,
            }
            for item in events
        ],
    }


@router.get("/{mandate_id}/acquisitions")
def acquisitions(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from app.domain.mandates import TelegraphCall
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).all()
    output=[]
    for t in tasks:
        call=session.query(TelegraphCall).filter_by(acquisition_id=t.acquisition_id).one_or_none()
        output.append({"acquisition_id":t.acquisition_id,"status":t.status,"requested_intent":t.requested_intent,"intent":call.intent if call else None,"miner_id":call.miner_id if call else None,"miner_name":call.miner_name if call else None,"signal_hash":call.signal_hash if call else None,"cost_usd":float(call.cost_usd) if call and call.cost_usd is not None else None,"duration_ms":call.duration_ms if call else None})
    return {"mandate_id": mandate_id, "acquisitions": output}

@router.get("/{mandate_id}/evidence")
def evidence(mandate_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    from app.domain.mandates import Evidence
    return [{"evidence_id":e.evidence_id,"admissibility":e.admissibility,"provenance_status":e.provenance_status,"content_hash":e.content_hash,"source_intent":e.source_intent,"source_miner_id":e.source_miner_id,"source_signal_hash":e.source_signal_hash,"limitation_codes":e.limitation_codes,"normalized_payload":e.normalized_payload} for e in session.query(Evidence).filter_by(mandate_id=mandate_id)]
@router.get("/{mandate_id}/evaluation")
def evaluation(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from app.domain.mandates import StructuralEvaluation
    e=session.query(StructuralEvaluation).filter_by(mandate_id=mandate_id).order_by(StructuralEvaluation.created_at.desc()).first()
    if not e: raise HTTPException(404,"evaluation not found")
    return {"evaluation_id":e.evaluation_id,"evaluator_version":e.evaluator_version,"evidence_set_hash":e.evidence_set_hash,"structural_state":e.structural_state,"limitation_codes":e.limitation_codes,"contradiction_codes":e.contradiction_codes}
@router.get("/{mandate_id}/decision")
def decision(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from app.domain.mandates import Decision
    d=session.query(Decision).filter_by(mandate_id=mandate_id).order_by(Decision.created_at.desc()).first()
    if not d: raise HTTPException(404,"decision not found")
    return {"decision_id":d.decision_id,"state":d.state,"policy_version":d.policy_version,"reason_codes":d.reason_codes,"evidence_set_hash":d.evidence_set_hash,"evaluation_id":d.evaluation_id}
@router.get("/{mandate_id}/replay")
def replay(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from app.pramagraph.replay import replay as run
    return run(session, mandate_id)
@router.get("/{mandate_id}/ticket")
def ticket(mandate_id: str, session: Session = Depends(get_session)):
    from app.domain.mandates import Ticket
    t=session.query(Ticket).filter_by(mandate_id=mandate_id).first()
    if not t: raise HTTPException(404,"ticket not found")
    return {"ticket_id":t.ticket_id,"mandate_id":t.mandate_id,"schema_version":t.schema_version,"ticket_hash":t.ticket_hash,"anchor_status":t.anchor_status,"canonical_payload":t.canonical_payload}
