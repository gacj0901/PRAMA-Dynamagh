"""O_EVIDENCE_PROVENANCE v0.1.

This observer is deliberately downstream of the persisted evidence lineage and
upstream of no decision path.  It records only the binary discontinuity of the
frozen Mandate -> AcquisitionTask -> TelegraphCall -> Evidence chain and feeds
that dimensionless stream to the certified PRAMA Protokol v0.3.0 reference
implementation in ``app.prama_v030``.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from typing import Any
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AcquisitionTask,
    Evidence,
    Mandate,
    OEvidenceProvenanceContextState,
    OEvidenceProvenanceContract,
    OEvidenceProvenanceGlobalState,
    OEvidenceProvenanceObservation,
    TelegraphCall,
)
from app.persistence.database import SessionLocal
from app.prama_v030 import KernelConfigV3, KernelV3, causal_conditional_mean
from app.pramagraph.evaluation import digest


OBSERVER_ID = "o-evidence-provenance-v0.1"
OBSERVER_VERSION = "0.1"
MIN_CONTEXT_COUNT = 2
MIN_GLOBAL_COUNT = 2
CAPABILITY = "K1 memory-only structural trajectory observation of persisted provenance discontinuity"
BOUNDARY = ["Mandate", "AcquisitionTask", "TelegraphCall", "Evidence"]
CONTEXT_FIELDS = ["miner_id", "intent"]
SIGMA_OP_STATUS = "NOT_APPLICABLE"
U_LAMBDA_STATUS = "NOT_APPLICABLE"
KERNEL_CONFIG_VALUES = {
    "h": 1.0,
    "tau": 336.0,
    "theta_scale": 2.0,
    "lambda_0": 1.0,
    "lambda_min": 0.1,
    "lambda_max": 1.0,
    "kappa_v3": 9.957514604354753e-7,
    "g_smooth": 24,
    "delta_ref": 1.0,
}
KERNEL_CONFIG = KernelConfigV3(**KERNEL_CONFIG_VALUES)


def _json_value(value: Any) -> Any:
    """Convert numpy/scalar values to stable JSON-compatible primitives."""

    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _kernel_state(kernel: KernelV3) -> dict[str, Any]:
    return {
        "r": kernel._r,
        "xi": kernel._xi,
        "A": kernel._A,
        "lambda": kernel._lambda,
        "theta": kernel._theta,
        "started": kernel._started,
        "input_index": kernel._input_index,
        "m_ring": list(kernel._m_ring),
        "ring_pos": kernel._ring_pos,
        "ring_len": kernel._ring_len,
        "ring_sum": kernel._ring_sum,
        "smooth_m_prev": kernel._smooth_m_prev,
        "resummation_count": kernel._resummation_count,
        "lambda_sum_A": kernel._lambda_sum_A,
        "lambda_sum_u": kernel._lambda_sum_u,
        "lambda_sum_pi": kernel._lambda_sum_pi,
        "lambda_step_residual": kernel._lambda_step_residual,
        "lambda_ledger_residual": kernel._lambda_ledger_residual,
    }


def _kernel_from_state(state: dict[str, Any] | None) -> KernelV3:
    kernel = KernelV3(KERNEL_CONFIG)
    if not state:
        return kernel
    kernel._r = float(state["r"])
    kernel._xi = float(state["xi"])
    kernel._A = float(state["A"])
    kernel._lambda = float(state["lambda"])
    kernel._theta = float(state["theta"])
    kernel._started = bool(state["started"])
    kernel._input_index = int(state["input_index"])
    kernel._m_ring = [float(value) for value in state["m_ring"]]
    kernel._ring_pos = int(state["ring_pos"])
    kernel._ring_len = int(state["ring_len"])
    kernel._ring_sum = float(state["ring_sum"])
    kernel._smooth_m_prev = None if state["smooth_m_prev"] is None else float(state["smooth_m_prev"])
    kernel._resummation_count = int(state["resummation_count"])
    kernel._lambda_sum_A = float(state["lambda_sum_A"])
    kernel._lambda_sum_u = float(state["lambda_sum_u"])
    kernel._lambda_sum_pi = float(state["lambda_sum_pi"])
    kernel._lambda_step_residual = float(state["lambda_step_residual"])
    kernel._lambda_ledger_residual = float(state["lambda_ledger_residual"])
    return kernel


def _kernel_output(kernel: KernelV3, row: Any) -> dict[str, Any]:
    audit = kernel.numeric_audit
    return {
        "row": {key: _json_value(value) for key, value in row.as_dict().items()},
        "numeric_audit": {
            field.name: _json_value(getattr(audit, field.name))
            for field in fields(audit)
        },
        "compatibility_inputs": {
            "u_lambda": 0.0,
            "sigma_op": None,
            "u_lambda_status": U_LAMBDA_STATUS,
            "sigma_op_status": SIGMA_OP_STATUS,
        },
    }


def _context(miner_id: str | None, intent: str | None) -> tuple[str, str] | None:
    if not miner_id or not intent:
        return None
    return str(miner_id), str(intent)


def _causal_expected(values: list[float], contexts: list[tuple[str, str]], current: tuple[str, str]) -> float | None:
    all_values = np.asarray(values + [values[-1] if values else 0.0], dtype=np.float64)
    all_contexts = np.asarray(contexts + [current], dtype=object)
    expected = causal_conditional_mean(
        all_values,
        all_contexts,
        min_context_count=MIN_CONTEXT_COUNT,
        min_global_count=MIN_GLOBAL_COUNT,
    )[-1]
    return None if not np.isfinite(expected) else float(expected)


def _prior_causal_input(session: Session, sequence: int, context: tuple[str, str]) -> tuple[list[float], list[tuple[str, str]]]:
    rows = session.scalars(
        select(OEvidenceProvenanceObservation)
        .where(
            OEvidenceProvenanceObservation.observer_id == OBSERVER_ID,
            OEvidenceProvenanceObservation.sequence < sequence,
            OEvidenceProvenanceObservation.miner_id.is_not(None),
            OEvidenceProvenanceObservation.intent.is_not(None),
        )
        .order_by(OEvidenceProvenanceObservation.sequence)
    ).all()
    values = [float(row.omega) for row in rows]
    contexts = [(str(row.miner_id), str(row.intent)) for row in rows]
    return values, contexts


def _lineage(session: Session, telegraph_call_id: str) -> dict[str, Any] | None:
    call = session.get(TelegraphCall, telegraph_call_id)
    if call is None:
        return None
    mandate = session.get(Mandate, call.mandate_id)
    task = session.get(AcquisitionTask, call.acquisition_id)
    evidence = session.scalar(
        select(Evidence).where(Evidence.telegraph_call_id == call.telegraph_call_id)
    )
    required = [
        mandate is not None and task is not None and task.mandate_id == mandate.mandate_id,
        mandate is not None and call.mandate_id == mandate.mandate_id,
        task is not None and call.acquisition_id == task.acquisition_id,
        mandate is not None and evidence is not None and evidence.mandate_id == mandate.mandate_id,
        evidence is not None and evidence.acquisition_id == call.acquisition_id,
        evidence is not None and evidence.telegraph_call_id == call.telegraph_call_id,
        evidence is not None and evidence.source_intent is not None and call.intent is not None and evidence.source_intent == call.intent,
        evidence is not None and evidence.source_miner_id is not None and call.miner_id is not None and evidence.source_miner_id == call.miner_id,
        evidence is not None and evidence.source_signal_hash is not None and call.signal_hash is not None and evidence.source_signal_hash == call.signal_hash,
        call.status == "SUCCEEDED"
        and task is not None
        and task.status == "SUCCEEDED"
        and task.completed_at is not None
        and call.completed_at is not None
        and bool(call.intent)
        and bool(call.miner_id)
        and bool(call.signal_hash),
    ]
    observed_at = call.completed_at or call.created_at
    return {
        "call": call,
        "mandate": mandate,
        "task": task,
        "evidence": evidence,
        "omega": 0 if all(required) else 1,
        "source_artifact_ids": {
            "mandate_id": mandate.mandate_id if mandate else call.mandate_id,
            "acquisition_id": task.acquisition_id if task else call.acquisition_id,
            "telegraph_call_id": call.telegraph_call_id,
            "evidence_id": evidence.evidence_id if evidence else None,
        },
        "miner_id": call.miner_id,
        "intent": call.intent,
        "observed_at": observed_at,
    }


def _contract(session: Session) -> OEvidenceProvenanceContract:
    contract = session.get(OEvidenceProvenanceContract, OBSERVER_ID, with_for_update=True)
    if contract is None:
        raise RuntimeError("O_EVIDENCE_PROVENANCE contract is not installed")
    if contract.observer_version != OBSERVER_VERSION or contract.min_context_count != MIN_CONTEXT_COUNT or contract.min_global_count != MIN_GLOBAL_COUNT:
        raise RuntimeError("O_EVIDENCE_PROVENANCE contract mismatch")
    return contract


def _global_state(session: Session) -> OEvidenceProvenanceGlobalState:
    state = session.get(OEvidenceProvenanceGlobalState, OBSERVER_ID, with_for_update=True)
    if state is None:
        state = OEvidenceProvenanceGlobalState(observer_id=OBSERVER_ID)
        session.add(state)
        session.flush()
    return state


def _context_state(session: Session, context: tuple[str, str]) -> OEvidenceProvenanceContextState:
    miner_id, intent = context
    state = session.get(OEvidenceProvenanceContextState, (OBSERVER_ID, miner_id, intent), with_for_update=True)
    if state is None:
        state = OEvidenceProvenanceContextState(observer_id=OBSERVER_ID, miner_id=miner_id, intent=intent)
        session.add(state)
        session.flush()
    return state


def _result(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "observer_id": OBSERVER_ID, "observer_version": OBSERVER_VERSION, **values}


def observe_telegraph_call(session: Session, telegraph_call_id: str) -> dict[str, Any]:
    """Record one completed call, with no dependency on downstream decisions."""

    existing = session.scalar(
        select(OEvidenceProvenanceObservation).where(
            OEvidenceProvenanceObservation.observer_id == OBSERVER_ID,
            OEvidenceProvenanceObservation.telegraph_call_id == telegraph_call_id,
        )
    )
    if existing is not None:
        return _result("ALREADY_RECORDED", observation_id=existing.observation_id, observation_hash=existing.observation_hash)

    lineage = _lineage(session, telegraph_call_id)
    if lineage is None:
        return _result("SOURCE_NOT_FOUND")
    if lineage["observed_at"] is None:
        return _result("INCOMPLETE_SOURCE")

    contract = _contract(session)
    global_state = _global_state(session)
    if global_state.last_observed_at is not None and lineage["observed_at"] < global_state.last_observed_at:
        return _result("OUT_OF_ORDER", observed_at=lineage["observed_at"].isoformat())

    context = _context(lineage["miner_id"], lineage["intent"])
    context_state = _context_state(session, context) if context is not None else None
    context_count = context_state.observation_count if context_state is not None else 0
    global_count = global_state.observation_count
    if context is None:
        support_status = "INSUFFICIENT_SUPPORT"
        expected = None
    elif context_count >= contract.min_context_count:
        support_status = "CONTEXT_MEAN"
        values, contexts = _prior_causal_input(session, global_state.next_sequence, context)
        expected = _causal_expected(values, contexts, context)
    elif global_count >= contract.min_global_count:
        support_status = "GLOBAL_MEAN"
        values, contexts = _prior_causal_input(session, global_state.next_sequence, context)
        expected = _causal_expected(values, contexts, context)
    else:
        support_status = "WARMUP"
        expected = None

    kernel_output = None
    if expected is not None and context_state is not None:
        persisted_kernel = context_state.kernel_state or {}
        internal_state = persisted_kernel.get("internal") if "internal" in persisted_kernel else persisted_kernel
        kernel = _kernel_from_state(internal_state)
        row = kernel.step(float(lineage["omega"]), expected, 0.0, None)
        if row is None:
            raise RuntimeError("certified KernelV3 unexpectedly excluded supported row")
        kernel_output = _kernel_output(kernel, row)
        context_state.kernel_state = {
            "internal": _kernel_state(kernel),
            "last_output": kernel_output,
        }

    sequence = global_state.next_sequence
    source_ids = lineage["source_artifact_ids"]
    payload = {
        "observer_id": OBSERVER_ID,
        "observer_version": OBSERVER_VERSION,
        "sequence": sequence,
        "observed_at": lineage["observed_at"].isoformat(),
        "source_artifact_ids": source_ids,
        "context": {"miner_id": lineage["miner_id"], "intent": lineage["intent"]},
        "omega": lineage["omega"],
        "expected": expected,
        "support_status": support_status,
        "context_count_before": context_count,
        "global_count_before": global_count,
        "kernel_output": kernel_output,
        "normalization": "identity",
        "sigma_op_status": SIGMA_OP_STATUS,
        "u_lambda_status": U_LAMBDA_STATUS,
        "capability": CAPABILITY,
    }
    observation_hash = digest(payload)
    observation = OEvidenceProvenanceObservation(
        observation_id=str(uuid.uuid4()),
        observer_id=OBSERVER_ID,
        sequence=sequence,
        observed_at=lineage["observed_at"],
        mandate_id=source_ids["mandate_id"],
        acquisition_id=source_ids["acquisition_id"],
        telegraph_call_id=source_ids["telegraph_call_id"],
        evidence_id=source_ids["evidence_id"],
        miner_id=lineage["miner_id"],
        intent=lineage["intent"],
        omega=lineage["omega"],
        expected=expected,
        support_status=support_status,
        context_count_before=context_count,
        global_count_before=global_count,
        source_artifact_ids=source_ids,
        kernel_output=kernel_output,
        observation_hash=observation_hash,
    )
    session.add(observation)
    global_state.observation_count += 1 if context is not None else 0
    global_state.omega_sum = (global_state.omega_sum or Decimal("0")) + Decimal(str(lineage["omega"])) if context is not None else global_state.omega_sum
    global_state.next_sequence += 1
    global_state.last_observed_at = lineage["observed_at"]
    if context_state is not None:
        context_state.observation_count += 1
        context_state.omega_sum = (context_state.omega_sum or Decimal("0")) + Decimal(str(lineage["omega"]))
        context_state.last_observed_at = lineage["observed_at"]
    session.flush()
    return _result(
        "RECORDED",
        observation_id=observation.observation_id,
        sequence=sequence,
        observation_hash=observation_hash,
        omega=lineage["omega"],
        expected=expected,
        support_status=support_status,
        kernel_output=kernel_output,
    )


def observe_mandate_shadow(mandate_id: str) -> list[dict[str, Any]]:
    """Observe completed calls for a mandate in an independent shadow session."""

    session = SessionLocal()
    try:
        call_ids = session.scalars(
            select(TelegraphCall.telegraph_call_id)
            .where(TelegraphCall.mandate_id == mandate_id, TelegraphCall.completed_at.is_not(None))
            .order_by(TelegraphCall.completed_at, TelegraphCall.telegraph_call_id)
        ).all()
        results = [observe_telegraph_call(session, call_id) for call_id in call_ids]
        session.commit()
        return results
    finally:
        session.close()


def list_observations(
    session: Session,
    *,
    miner_id: str | None = None,
    intent: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[OEvidenceProvenanceObservation]:
    query = select(OEvidenceProvenanceObservation).where(
        OEvidenceProvenanceObservation.observer_id == OBSERVER_ID
    )
    if miner_id is not None:
        query = query.where(OEvidenceProvenanceObservation.miner_id == miner_id)
    if intent is not None:
        query = query.where(OEvidenceProvenanceObservation.intent == intent)
    if start is not None:
        query = query.where(OEvidenceProvenanceObservation.observed_at >= start)
    if end is not None:
        query = query.where(OEvidenceProvenanceObservation.observed_at <= end)
    return list(session.scalars(query.order_by(OEvidenceProvenanceObservation.sequence)).all())


def replay_provenance(session: Session) -> dict[str, Any]:
    """Recompute observation content and KernelV3 state without mutating storage."""

    stored = list_observations(session)
    context_kernels: dict[tuple[str, str], KernelV3] = {}
    values: list[float] = []
    contexts: list[tuple[str, str]] = []
    context_counts: dict[tuple[str, str], int] = {}
    hashes: list[str] = []
    match_count = 0
    valid = True
    for stored_row in stored:
        lineage = _lineage(session, stored_row.telegraph_call_id or "")
        if lineage is None:
            valid = False
            continue
        context = _context(lineage["miner_id"], lineage["intent"])
        context_count = context_counts.get(context, 0) if context is not None else 0
        global_count = len(values)
        if context is None:
            support_status, expected = "INSUFFICIENT_SUPPORT", None
        elif context_count >= MIN_CONTEXT_COUNT:
            support_status = "CONTEXT_MEAN"
            expected = _causal_expected(values, contexts, context)
        elif global_count >= MIN_GLOBAL_COUNT:
            support_status = "GLOBAL_MEAN"
            expected = _causal_expected(values, contexts, context)
        else:
            support_status, expected = "WARMUP", None
        kernel_output = None
        if expected is not None and context is not None:
            kernel = context_kernels.setdefault(context, KernelV3(KERNEL_CONFIG))
            row = kernel.step(float(lineage["omega"]), expected, 0.0, None)
            kernel_output = _kernel_output(kernel, row)
        payload = {
            "observer_id": OBSERVER_ID,
            "observer_version": OBSERVER_VERSION,
            "sequence": stored_row.sequence,
            "observed_at": stored_row.observed_at.isoformat(),
            "source_artifact_ids": lineage["source_artifact_ids"],
            "context": {"miner_id": lineage["miner_id"], "intent": lineage["intent"]},
            "omega": lineage["omega"],
            "expected": expected,
            "support_status": support_status,
            "context_count_before": context_count,
            "global_count_before": global_count,
            "kernel_output": kernel_output,
            "normalization": "identity",
            "sigma_op_status": SIGMA_OP_STATUS,
            "u_lambda_status": U_LAMBDA_STATUS,
            "capability": CAPABILITY,
        }
        recomputed_hash = digest(payload)
        hashes.append(recomputed_hash)
        matches = recomputed_hash == stored_row.observation_hash
        match_count += 1 if matches else 0
        valid = valid and matches
        if context is not None:
            values.append(float(lineage["omega"]))
            contexts.append(context)
            context_counts[context] = context_count + 1
    return {
        "status": "VALID" if valid else "INVALID",
        "observation_count": len(stored),
        "match_count": match_count,
        "hashes": hashes,
    }
