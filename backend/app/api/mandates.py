from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domain.mandates import Mandate, MandateStatus, MandateTransition
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


@router.post("", response_model=MandateRead, status_code=status.HTTP_202_ACCEPTED)
def create_mandate(payload: MandateCreate, session: Session = Depends(get_session)) -> Mandate:
    mandate = Mandate(**payload.model_dump(), status=MandateStatus.RECEIVED.value)
    session.add(mandate)
    session.flush()
    session.add(MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="mandate created"))
    session.commit()
    session.refresh(mandate)
    return mandate


@router.get("/{mandate_id}", response_model=MandateRead)
def get_mandate(mandate_id: str, session: Session = Depends(get_session)) -> Mandate:
    mandate = session.get(Mandate, mandate_id)
    if mandate is None:
        raise HTTPException(status_code=404, detail="mandate not found")
    return mandate

