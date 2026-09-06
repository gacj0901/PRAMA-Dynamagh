from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.autonomy.service import PAID_MIN_CADENCE_SECONDS, status as autonomy_status, validate_policy
from app.domain.mandates import AutonomyPolicy, AutonomyRun
from app.persistence.database import get_session

router = APIRouter(prefix="/v1/autonomy", tags=["autonomy"])


class PolicyInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    version: str = "autonomy-policy-v0"
    mandate_template: dict[str, Any] = Field(default_factory=dict)
    acquisition_mode: str
    allow_telegraph_http: bool = False
    allow_erc8183: bool = False
    allow_anchor: bool = False
    strict_verification: bool = True
    read_only_replay: bool = False
    cadence_seconds: int = PAID_MIN_CADENCE_SECONDS
    dedupe_window_seconds: int = PAID_MIN_CADENCE_SECONDS
    max_usdc_per_run: Decimal = Decimal("0.050000")
    max_usdc_per_day: Decimal = Decimal("0.200000")
    max_runs_per_day: int = 4
    max_concurrent_runs: int = 1


class PolicyPatch(BaseModel):
    enabled: bool | None = None
    state: str | None = None
    mandate_template: dict[str, Any] | None = None
    allow_anchor: bool | None = None
    strict_verification: bool | None = None
    read_only_replay: bool | None = None
    cadence_seconds: int | None = None
    dedupe_window_seconds: int | None = None
    max_usdc_per_run: Decimal | None = None
    max_usdc_per_day: Decimal | None = None
    max_runs_per_day: int | None = None
    max_concurrent_runs: int | None = None


def _read(policy: AutonomyPolicy) -> dict:
    return {key: getattr(policy, key) for key in ("policy_id", "name", "enabled", "version", "mandate_template", "acquisition_mode", "allow_telegraph_http", "allow_erc8183", "allow_anchor", "strict_verification", "read_only_replay", "cadence_seconds", "dedupe_window_seconds", "max_usdc_per_run", "max_usdc_per_day", "max_runs_per_day", "max_concurrent_runs", "state", "created_at", "updated_at", "last_run_at", "next_run_at")}


def _run(run: AutonomyRun) -> dict:
    return {key: getattr(run, key) for key in ("run_id", "policy_id", "agent_identity_id", "scheduled_for", "idempotency_key", "state", "mandate_id", "erc8183_job_id", "ticket_id", "planned_cost_usdc", "actual_cost_usdc", "skip_reason", "failure_code", "started_at", "finished_at", "created_at", "updated_at")}


@router.post("/policies", status_code=201)
def create_policy(payload: PolicyInput, session: Session = Depends(get_session)):
    values = payload.model_dump()
    try:
        validate_policy(values)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    policy = AutonomyPolicy(**values, enabled=False, state="DRAFT")
    session.add(policy); session.commit(); session.refresh(policy)
    return _read(policy)


@router.get("/policies")
def list_policies(session: Session = Depends(get_session)):
    return [_read(policy) for policy in session.query(AutonomyPolicy).order_by(AutonomyPolicy.created_at)]


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str, session: Session = Depends(get_session)):
    policy = session.get(AutonomyPolicy, policy_id)
    if not policy: raise HTTPException(404, "AUTONOMY_POLICY_MISSING")
    return _read(policy)


@router.patch("/policies/{policy_id}")
def patch_policy(policy_id: str, payload: PolicyPatch, session: Session = Depends(get_session)):
    policy = session.get(AutonomyPolicy, policy_id)
    if not policy: raise HTTPException(404, "AUTONOMY_POLICY_MISSING")
    for key, value in payload.model_dump(exclude_none=True).items(): setattr(policy, key, value)
    try: validate_policy({key: getattr(policy, key) for key in PolicyInput.model_fields})
    except ValueError as error: raise HTTPException(422, str(error)) from error
    session.commit(); session.refresh(policy); return _read(policy)


@router.post("/policies/{policy_id}/enable")
def enable_policy(policy_id: str, session: Session = Depends(get_session)):
    policy = session.get(AutonomyPolicy, policy_id)
    if not policy: raise HTTPException(404, "AUTONOMY_POLICY_MISSING")
    try: validate_policy({key: getattr(policy, key) for key in PolicyInput.model_fields})
    except ValueError as error: raise HTTPException(422, str(error)) from error
    policy.enabled = True; policy.state = "ACTIVE"; session.commit(); return _read(policy)


@router.post("/policies/{policy_id}/disable")
def disable_policy(policy_id: str, session: Session = Depends(get_session)):
    policy = session.get(AutonomyPolicy, policy_id)
    if not policy: raise HTTPException(404, "AUTONOMY_POLICY_MISSING")
    policy.enabled = False; policy.state = "PAUSED"; session.commit(); return _read(policy)


@router.get("/runs")
def list_runs(session: Session = Depends(get_session)):
    return [_run(run) for run in session.query(AutonomyRun).order_by(AutonomyRun.scheduled_for.desc())]


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(AutonomyRun, run_id)
    if not run: raise HTTPException(404, "AUTONOMY_RUN_MISSING")
    return _run(run)


@router.get("/status")
def get_status(session: Session = Depends(get_session)):
    return autonomy_status(session)
