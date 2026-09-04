"""Narrow authenticated machine-to-machine mandate rail.

This router deliberately owns only mandate submission and read-only lineage
views.  It does not proxy Gateway, expose signer material, or accept any
chain, miner, recipient, calldata, anchor, or autonomy-policy command.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AcquisitionTask,
    Decision,
    Evidence,
    Mandate,
    MandateStatus,
    MandateTransition,
    M2MMandateRequest,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.persistence.database import get_session
from app.public_safety import m2m_max_workflow_usdc, reserve_m2m_spend
from app.workers.tasks import execute_acquisition

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/m2m", tags=["m2m"])


class M2MMandateCreate(BaseModel):
    """The complete M2M command surface; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1, max_length=255)
    client_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=20_000)
    mandate_type: str = Field(default="GENERAL", min_length=1, max_length=100)
    max_budget_usdc: Decimal = Field(default=Decimal("0.010000"), gt=0, max_digits=18, decimal_places=6)
    deadline: datetime | None = None


class M2MMandateRead(BaseModel):
    mandate_id: str
    idempotency_key: str | None = None
    agent_id: str
    client_id: str
    origin: str
    text: str
    mandate_type: str
    max_budget_usdc: Decimal
    deadline: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
    acquisitions: list[dict[str, Any]] = Field(default_factory=list)
    lineage: dict[str, Any] = Field(default_factory=dict)


def require_m2m_auth(request: Request) -> None:
    """Require the dedicated M2M Bearer secret, fail-closed if unconfigured."""

    expected = os.environ.get("PRAMA_M2M_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="M2M_AUTH_UNAVAILABLE")
    internal = os.environ.get("PRAMA_GATEWAY_INTERNAL_TOKEN")
    if internal and hmac.compare_digest(expected, internal):
        raise HTTPException(status_code=503, detail="M2M_AUTH_CONFIGURATION_INVALID")
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise HTTPException(status_code=401, detail="M2M_AUTH_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="M2M_AUTH_INVALID", headers={"WWW-Authenticate": "Bearer"})


def _request_hash(payload: M2MMandateCreate) -> str:
    material = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(material).hexdigest()


def _attribution(mandate: Mandate) -> dict[str, str]:
    return {"origin": mandate.origin, "agent_id": mandate.agent_id or "", "client_id": mandate.client_id or ""}


def _lineage(session: Session, mandate_id: str) -> dict[str, Any]:
    acquisitions = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).order_by(AcquisitionTask.ordinal).all()
    calls = session.query(TelegraphCall).filter_by(mandate_id=mandate_id).all()
    evidence = session.query(Evidence).filter_by(mandate_id=mandate_id).all()
    evaluation = session.query(StructuralEvaluation).filter_by(mandate_id=mandate_id).order_by(StructuralEvaluation.created_at.desc()).first()
    decision = session.query(Decision).filter_by(mandate_id=mandate_id).order_by(Decision.created_at.desc()).first()
    ticket = session.query(Ticket).filter_by(mandate_id=mandate_id).order_by(Ticket.created_at.desc()).first()
    return {
        "acquisition_ids": [item.acquisition_id for item in acquisitions],
        "telegraph_call_ids": [item.telegraph_call_id for item in calls],
        "evidence_ids": [item.evidence_id for item in evidence],
        "evaluation_id": evaluation.evaluation_id if evaluation else None,
        "decision_id": decision.decision_id if decision else None,
        "ticket_id": ticket.ticket_id if ticket else None,
    }


def _read_mandate(session: Session, mandate: Mandate, idempotency_key: str | None = None) -> dict[str, Any]:
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate.mandate_id).order_by(AcquisitionTask.ordinal).all()
    return {
        "mandate_id": mandate.mandate_id,
        "idempotency_key": idempotency_key,
        "agent_id": mandate.agent_id,
        "client_id": mandate.client_id,
        "origin": mandate.origin,
        "text": mandate.text,
        "mandate_type": mandate.mandate_type,
        "max_budget_usdc": mandate.max_budget_usdc,
        "deadline": mandate.deadline,
        "status": mandate.status,
        "created_at": mandate.created_at,
        "updated_at": mandate.updated_at,
        "acquisitions": [
            {
                "acquisition_id": item.acquisition_id,
                "status": item.status,
                "attempt_count": item.attempt_count,
                "failure_code": item.failure_code,
            }
            for item in tasks
        ],
        "lineage": _lineage(session, mandate.mandate_id),
    }


def _get_m2m_mandate(session: Session, mandate_id: str) -> Mandate:
    mandate = session.get(Mandate, mandate_id)
    if mandate is None or mandate.origin != "M2M":
        raise HTTPException(status_code=404, detail="M2M_MANDATE_MISSING")
    return mandate


@router.post("/mandates", response_model=M2MMandateRead, status_code=status.HTTP_202_ACCEPTED)
def create_m2m_mandate(
    payload: M2MMandateCreate,
    request: Request,
    session: Session = Depends(get_session),
    _: None = Depends(require_m2m_auth),
) -> dict[str, Any]:
    """Create exactly one bounded, attributed, idempotent M2M workflow."""

    idempotency_key = request.headers.get("idempotency-key", "")
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="M2M_IDEMPOTENCY_KEY_REQUIRED")
    request_hash = _request_hash(payload)
    existing = session.query(M2MMandateRequest).filter_by(idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        if existing.request_hash != request_hash or existing.agent_id != payload.agent_id or existing.client_id != payload.client_id:
            raise HTTPException(status_code=409, detail="M2M_IDEMPOTENCY_KEY_REUSED")
        mandate = _get_m2m_mandate(session, existing.mandate_id)
        return _read_mandate(session, mandate, existing.idempotency_key)

    if payload.max_budget_usdc > m2m_max_workflow_usdc():
        raise HTTPException(status_code=422, detail="M2M_WORKFLOW_BUDGET_EXCEEDED")
    try:
        mandate = Mandate(
            actor_id=f"m2m:{payload.client_id}:{payload.agent_id}",
            agent_id=payload.agent_id,
            client_id=payload.client_id,
            text=payload.text,
            mandate_type=payload.mandate_type,
            constraints={},
            max_budget_usdc=payload.max_budget_usdc,
            deadline=payload.deadline,
            status=MandateStatus.RECEIVED.value,
            origin="M2M",
        )
        session.add(mandate)
        session.flush()
        reserve_m2m_spend(session, mandate.mandate_id, payload.max_budget_usdc)
        task = AcquisitionTask(
            mandate_id=mandate.mandate_id,
            query=mandate.text,
            required=True,
            status="QUEUED",
            ordinal=0,
        )
        session.add(task)
        session.flush()
        session.add(
            M2MMandateRequest(
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                agent_id=payload.agent_id,
                client_id=payload.client_id,
                mandate_id=mandate.mandate_id,
            )
        )
        metadata = {**_attribution(mandate), "idempotency_key": idempotency_key}
        session.add_all(
            [
                MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="m2m mandate created"),
                UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_=metadata),
                UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_=metadata),
            ]
        )
        session.commit()
        session.refresh(mandate)
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        existing = session.query(M2MMandateRequest).filter_by(idempotency_key=idempotency_key).one_or_none()
        if existing is None:
            raise HTTPException(status_code=503, detail="M2M_IDEMPOTENCY_UNAVAILABLE")
        if existing.request_hash != request_hash or existing.agent_id != payload.agent_id or existing.client_id != payload.client_id:
            raise HTTPException(status_code=409, detail="M2M_IDEMPOTENCY_KEY_REUSED")
        return _read_mandate(session, _get_m2m_mandate(session, existing.mandate_id), existing.idempotency_key)
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="M2M_SPEND_AUTHORIZATION_UNAVAILABLE") from error

    # A broker failure after the durable commit leaves the reservation in place
    # and therefore cannot authorize an unaccounted paid retry.  A later retry
    # with the same key receives the same mandate and remains idempotent.
    try:
        execute_acquisition.delay(mandate.mandate_id, task.acquisition_id)
    except Exception:
        logger.warning("M2M_TASK_DISPATCH_UNCERTAIN mandate_id=%s", mandate.mandate_id)
        session.add(
            UsageEvent(
                mandate_id=mandate.mandate_id,
                event_type="M2M_TASK_DISPATCH_UNCERTAIN",
                metadata_=_attribution(mandate),
            )
        )
        session.commit()
    return _read_mandate(session, mandate, idempotency_key)


@router.get("/mandates/{mandate_id}", response_model=M2MMandateRead)
def get_m2m_mandate(
    mandate_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_m2m_auth),
) -> dict[str, Any]:
    mandate = _get_m2m_mandate(session, mandate_id)
    request_row = session.query(M2MMandateRequest).filter_by(mandate_id=mandate_id).one_or_none()
    return _read_mandate(session, mandate, request_row.idempotency_key if request_row else None)


@router.get("/tickets/{ticket_id}")
def get_m2m_ticket(
    ticket_id: str,
    session: Session = Depends(get_session),
    _: None = Depends(require_m2m_auth),
) -> dict[str, Any]:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="M2M_TICKET_MISSING")
    mandate = _get_m2m_mandate(session, ticket.mandate_id)
    decision = session.get(Decision, ticket.decision_id)
    evaluation = session.query(StructuralEvaluation).filter_by(mandate_id=mandate.mandate_id).order_by(StructuralEvaluation.created_at.desc()).first()
    evidence = session.query(Evidence).filter_by(mandate_id=mandate.mandate_id).order_by(Evidence.created_at).all()
    calls = session.query(TelegraphCall).filter_by(mandate_id=mandate.mandate_id).order_by(TelegraphCall.created_at).all()
    return {
        "ticket_id": ticket.ticket_id,
        "mandate_id": mandate.mandate_id,
        "agent_id": mandate.agent_id,
        "client_id": mandate.client_id,
        "origin": mandate.origin,
        "schema_version": ticket.schema_version,
        "ticket_hash": ticket.ticket_hash,
        "hash_algorithm": ticket.hash_algorithm,
        "anchor_status": ticket.anchor_status,
        "decision": None
        if decision is None
        else {
            "decision_id": decision.decision_id,
            "state": decision.state,
            "policy_version": decision.policy_version,
            "evidence_set_hash": decision.evidence_set_hash,
            "reason_codes": decision.reason_codes,
        },
        "evaluation": None
        if evaluation is None
        else {
            "evaluation_id": evaluation.evaluation_id,
            "evaluator": evaluation.evaluator,
            "evaluator_version": evaluation.evaluator_version,
            "evidence_set_hash": evaluation.evidence_set_hash,
            "structural_state": evaluation.structural_state,
            "limitation_codes": evaluation.limitation_codes,
            "contradiction_codes": evaluation.contradiction_codes,
        },
        "lineage": {
            "acquisition_ids": [item.acquisition_id for item in session.query(AcquisitionTask).filter_by(mandate_id=mandate.mandate_id).order_by(AcquisitionTask.ordinal)],
            "telegraph_call_ids": [item.telegraph_call_id for item in calls],
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "content_hash": item.content_hash,
                    "admissibility": item.admissibility,
                    "provenance_status": item.provenance_status,
                }
                for item in evidence
            ],
            "evaluation_id": evaluation.evaluation_id if evaluation else None,
            "decision_id": decision.decision_id if decision else None,
            "ticket_id": ticket.ticket_id,
        },
    }
