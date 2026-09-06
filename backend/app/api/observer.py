"""Least-privileged read-only operator status for shadow observers."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.mandates import Evidence, OEvidenceProvenanceContract, TelegraphCall
from app.observers.provenance import (
    OBSERVER_ID,
    OBSERVER_VERSION,
    replay_provenance,
    list_observations,
)
from app.persistence.database import get_session


EXPECTED_MIGRATION_HEAD = "0016_o_evidence_provenance"
router = APIRouter(prefix="/v1/operator/o-evidence", tags=["operator-observer"])


def require_observer_read_auth(request: Request) -> None:
    """Require the dedicated API-only read token and fail closed."""

    expected = os.environ.get("PRAMA_OBSERVER_READ_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="OBSERVER_READ_AUTH_UNAVAILABLE")
    for other_name in (
        "PRAMA_M2M_API_TOKEN",
        "PRAMA_GATEWAY_INTERNAL_TOKEN",
        "TELEGRAPH_SIGNER_PRIVATE_KEY",
    ):
        other = os.environ.get(other_name)
        if other and hmac.compare_digest(expected, other):
            raise HTTPException(status_code=503, detail="OBSERVER_READ_AUTH_CONFIGURATION_INVALID")
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OBSERVER_READ_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OBSERVER_READ_AUTH_INVALID",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_observer_backfill_auth(request: Request) -> None:
    """Require the temporary backfill-only secret, fail-closed."""

    expected = os.environ.get("PRAMA_OBSERVER_BACKFILL_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="OBSERVER_BACKFILL_AUTH_UNAVAILABLE")
    for other_name in (
        "PRAMA_OBSERVER_READ_TOKEN",
        "PRAMA_M2M_API_TOKEN",
        "PRAMA_GATEWAY_INTERNAL_TOKEN",
        "TELEGRAPH_SIGNER_PRIVATE_KEY",
    ):
        other = os.environ.get(other_name)
        if other and hmac.compare_digest(expected, other):
            raise HTTPException(status_code=503, detail="OBSERVER_BACKFILL_AUTH_CONFIGURATION_INVALID")
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OBSERVER_BACKFILL_AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OBSERVER_BACKFILL_AUTH_INVALID",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _context_id(miner_id: str, intent: str) -> str:
    material = f"{miner_id}\0{intent}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _status_snapshot(session: Session) -> dict[str, Any]:
    contract = session.get(OEvidenceProvenanceContract, OBSERVER_ID)
    migration_head = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()

    eligible_evidence_count = session.scalar(
        select(func.count(Evidence.evidence_id))
        .select_from(Evidence)
        .join(TelegraphCall, Evidence.telegraph_call_id == TelegraphCall.telegraph_call_id)
        .where(TelegraphCall.completed_at.is_not(None))
    ) or 0

    observations = list_observations(session)
    warmup_count = sum(row.support_status in {"WARMUP", "INSUFFICIENT_SUPPORT"} for row in observations)
    kernel_evaluated_count = sum(row.kernel_output is not None for row in observations)
    omega_0_count = sum(int(row.omega) == 0 for row in observations)
    omega_1_count = sum(int(row.omega) == 1 for row in observations)

    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"observation_count": 0, "omega_0_count": 0, "omega_1_count": 0}
    )
    for row in observations:
        if row.miner_id is None or row.intent is None:
            continue
        bucket = grouped[(str(row.miner_id), str(row.intent))]
        bucket["observation_count"] += 1
        bucket[f"omega_{int(row.omega)}_count"] += 1
    context_summaries = [
        {
            "context_id": _context_id(miner_id, intent),
            "intent": intent,
            **values,
        }
        for (miner_id, intent), values in sorted(grouped.items())
    ]

    replay = replay_provenance(session)
    latest_gamma = None
    for row in reversed(observations):
        if row.kernel_output is not None:
            latest_gamma = row.kernel_output.get("row")
            break

    return {
        "observer_version": OBSERVER_VERSION,
        "migration": {
            "expected_head": EXPECTED_MIGRATION_HEAD,
            "current_head": migration_head,
            "ready": migration_head == EXPECTED_MIGRATION_HEAD,
            "contract_persisted": contract is not None,
        },
        "eligible_evidence_count": int(eligible_evidence_count),
        "warmup_count": warmup_count,
        "kernel_evaluated_count": kernel_evaluated_count,
        "omega_0_count": omega_0_count,
        "omega_1_count": omega_1_count,
        "context_count": len(context_summaries),
        "contexts": context_summaries,
        "latest_gamma": latest_gamma,
        "replay_checked_count": replay["observation_count"],
        "replay_match_count": replay["match_count"],
        "deterministic_hash_match": replay["status"] == "VALID" and replay["observation_count"] == replay["match_count"],
        "shadow_mode": True,
        "decision_gate_unchanged": True,
    }


@router.get("/provenance/status")
def provenance_status(
    _: None = Depends(require_observer_read_auth),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return bounded observer metadata only; never mutates source or observer state."""

    try:
        return _status_snapshot(session)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="OBSERVER_STATUS_UNAVAILABLE") from error


@router.post("/provenance/backfill")
def provenance_backfill(
    _: None = Depends(require_observer_backfill_auth),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """One-time bounded backfill of eligible persisted source rows only."""

    try:
        call_ids = session.scalars(
            select(TelegraphCall.telegraph_call_id)
            .join(Evidence, Evidence.telegraph_call_id == TelegraphCall.telegraph_call_id)
            .where(TelegraphCall.completed_at.is_not(None))
            .order_by(TelegraphCall.completed_at, TelegraphCall.telegraph_call_id)
        ).all()
        results = [observe_telegraph_call(session, call_id) for call_id in call_ids]
        session.commit()
        return {
            "eligible_evidence_count": len(call_ids),
            "rows_created": sum(result.get("status") == "RECORDED" for result in results),
            "rows_already_present": sum(result.get("status") == "ALREADY_RECORDED" for result in results),
            "rows_out_of_order": sum(result.get("status") == "OUT_OF_ORDER" for result in results),
        }
    except SQLAlchemyError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="OBSERVER_BACKFILL_UNAVAILABLE") from error
