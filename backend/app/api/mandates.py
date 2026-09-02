from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domain.mandates import AcquisitionTask, AcquisitionStatus, Mandate, MandateStatus, MandateTransition, UsageEvent
from app.workers.tasks import execute_acquisition
from app.persistence.database import get_session

router = APIRouter(prefix="/v1/mandates", tags=["mandates"])


class MandateCreate(BaseModel):
    actor_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=20_000)
    mandate_type: str = Field(default="GENERAL", min_length=1, max_length=100)
    constraints: dict[str, Any] = Field(default_factory=dict)
    max_budget_usdc: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    deadline: datetime | None = None


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
    created_at: datetime
    updated_at: datetime
    acquisitions: list[dict[str, Any]] = []


@router.post("", response_model=MandateRead, status_code=status.HTTP_202_ACCEPTED)
def create_mandate(payload: MandateCreate, session: Session = Depends(get_session)) -> Mandate:
    mandate = Mandate(**payload.model_dump(), status=MandateStatus.RECEIVED.value)
    session.add(mandate)
    session.flush()
    task = AcquisitionTask(mandate_id=mandate.mandate_id, query=mandate.text, required=True, status=AcquisitionStatus.PENDING.value, ordinal=0)
    session.add_all([MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="mandate created"), task, UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_={})])
    session.commit()
    session.refresh(mandate)
    session.refresh(task)
    task.status = AcquisitionStatus.QUEUED.value; session.add(UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_={})); session.commit()
    execute_acquisition.delay(mandate.mandate_id, task.acquisition_id)
    mandate.acquisitions = []
    return mandate


@router.get("/{mandate_id}", response_model=MandateRead)
def get_mandate(mandate_id: str, session: Session = Depends(get_session)) -> Mandate:
    mandate = session.get(Mandate, mandate_id)
    if mandate is None:
        raise HTTPException(status_code=404, detail="mandate not found")
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).all()
    mandate.acquisitions = [{"acquisition_id": t.acquisition_id, "status": t.status, "attempt_count": t.attempt_count, "failure_code": t.failure_code} for t in tasks]
    return mandate


@router.get("/{mandate_id}/acquisitions")
def acquisitions(mandate_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    from app.domain.mandates import TelegraphCall
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).all()
    output=[]
    for t in tasks:
        call=session.query(TelegraphCall).filter_by(acquisition_id=t.acquisition_id).one_or_none()
        output.append({"acquisition_id":t.acquisition_id,"status":t.status,"intent":call.intent if call else None,"miner_id":call.miner_id if call else None,"miner_name":call.miner_name if call else None,"signal_hash":call.signal_hash if call else None,"cost_usd":float(call.cost_usd) if call and call.cost_usd is not None else None,"duration_ms":call.duration_ms if call else None})
    return {"mandate_id": mandate_id, "acquisitions": output}
