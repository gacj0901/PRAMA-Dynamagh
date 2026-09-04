"""Persistent, fail-closed autonomy scheduling.

REPLAY_ONLY is always DB-only.  TELEGRAPH_HTTP is executable only when both
the global switch and the explicitly enabled policy permit the bounded rail.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.domain.mandates import (
    AcquisitionStatus,
    AcquisitionTask,
    AutonomyPolicy,
    AutonomyRun,
    ERC8183Job,
    Mandate,
    MandateStatus,
    MandateTransition,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.erc8183.evidence import replay_persisted
from app.public_safety import M2M_MAX_WORKFLOW_USDC, reserve_autonomous_spend

PAID_MIN_CADENCE_SECONDS = 900
MODES = {"TELEGRAPH_HTTP", "TELEGRAPH_ERC8183", "REPLAY_ONLY"}
ACTIVE_RUN_STATES = {"SCHEDULED", "CLAIMED", "RUNNING", "WAITING_EXTERNAL"}
FORBIDDEN_TEMPLATE_KEYS = {"private_key", "secret", "credential", "calldata", "spender", "callback"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def global_enabled() -> bool:
    return os.environ.get("AUTONOMY_GLOBAL_ENABLED", "false").lower() == "true"


def validate_policy(values: dict) -> None:
    mode = values.get("acquisition_mode")
    if mode not in MODES:
        raise ValueError("AUTONOMY_MODE_INVALID")
    cadence = int(values.get("cadence_seconds", PAID_MIN_CADENCE_SECONDS))
    if cadence < PAID_MIN_CADENCE_SECONDS:
        raise ValueError("AUTONOMY_CADENCE_TOO_FAST")
    if int(values.get("dedupe_window_seconds", cadence)) < cadence:
        raise ValueError("AUTONOMY_DEDUPE_WINDOW_INVALID")
    if int(values.get("max_runs_per_day", 0)) < 1 or int(values.get("max_concurrent_runs", 0)) < 1:
        raise ValueError("AUTONOMY_LIMIT_INVALID")
    for field in ("max_usdc_per_run", "max_usdc_per_day"):
        if Decimal(str(values.get(field, "0"))) < 0:
            raise ValueError("AUTONOMY_BUDGET_INVALID")
    if mode == "TELEGRAPH_HTTP" and not values.get("allow_telegraph_http", False):
        raise ValueError("AUTONOMY_HTTP_NOT_ALLOWED")
    if mode == "TELEGRAPH_ERC8183" and not values.get("allow_erc8183", False):
        raise ValueError("AUTONOMY_ERC8183_NOT_ALLOWED")
    if values.get("state", "DRAFT") not in {"DRAFT", "ACTIVE", "PAUSED", "DISABLED"}:
        raise ValueError("AUTONOMY_STATE_INVALID")
    _validate_template(values.get("mandate_template", {}))


def _validate_template(value: object) -> None:
    """Policies describe a mandate, never a signing or gateway capability."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(forbidden in normalized for forbidden in FORBIDDEN_TEMPLATE_KEYS):
                raise ValueError("AUTONOMY_TEMPLATE_FORBIDDEN_FIELD")
            _validate_template(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_template(nested)


def execution_slot(policy: AutonomyPolicy, when: datetime) -> datetime:
    instant = when.astimezone(timezone.utc)
    seconds = int(instant.timestamp())
    return datetime.fromtimestamp(seconds - seconds % policy.cadence_seconds, tz=timezone.utc)


def idempotency_key(policy: AutonomyPolicy, slot: datetime) -> str:
    material = f"{policy.policy_id}:{policy.version}:{slot.astimezone(timezone.utc).isoformat()}".encode()
    return hashlib.sha256(material).hexdigest()


def _event(session, run: AutonomyRun, event_type: str) -> None:
    existing = next((item for item in session.query(UsageEvent).filter_by(event_type=event_type) if item.metadata_.get("autonomy_run_id") == run.run_id), None)
    if existing is None:
        session.add(UsageEvent(mandate_id=run.mandate_id, event_type=event_type, metadata_={"autonomy_run_id": run.run_id, "policy_id": run.policy_id}))


def _day_bounds(instant: datetime) -> tuple[datetime, datetime]:
    start = instant.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _planned_cost(policy: AutonomyPolicy) -> Decimal:
    return Decimal("0.000000") if policy.acquisition_mode == "REPLAY_ONLY" else Decimal(policy.max_usdc_per_run)


def _budget_reason(session, policy: AutonomyPolicy, instant: datetime, planned: Decimal) -> str | None:
    start, end = _day_bounds(instant)
    day_runs = session.query(AutonomyRun).filter(AutonomyRun.policy_id == policy.policy_id, AutonomyRun.scheduled_for >= start, AutonomyRun.scheduled_for < end).all()
    if len(day_runs) >= policy.max_runs_per_day:
        return "DAILY_RUN_CAP"
    active = [run for run in day_runs if run.state in ACTIVE_RUN_STATES]
    if len(active) >= policy.max_concurrent_runs:
        return "CONCURRENCY_CAP"
    spent = sum((Decimal(run.actual_cost_usdc) for run in day_runs if run.state == "COMPLETED"), Decimal("0"))
    reserved = sum((Decimal(run.planned_cost_usdc) for run in active), Decimal("0"))
    if planned > Decimal(policy.max_usdc_per_run):
        return "RUN_BUDGET_CAP"
    if spent + reserved + planned > Decimal(policy.max_usdc_per_day):
        return "DAILY_BUDGET_CAP"
    return None


def schedule_due(session, policy: AutonomyPolicy, instant: datetime | None = None, *, global_switch: bool | None = None) -> AutonomyRun | None:
    instant = instant or now()
    enabled = global_enabled() if global_switch is None else global_switch
    if not enabled or not policy.enabled or policy.state != "ACTIVE":
        return None
    slot = execution_slot(policy, instant)
    key = idempotency_key(policy, slot)
    existing = session.query(AutonomyRun).filter_by(idempotency_key=key).one_or_none()
    if existing:
        return existing
    if policy.next_run_at and instant < policy.next_run_at:
        return None
    planned = _planned_cost(policy)
    reason = _budget_reason(session, policy, instant, planned)
    run = AutonomyRun(policy_id=policy.policy_id, scheduled_for=slot, idempotency_key=key, state="SKIPPED" if reason else "SCHEDULED", planned_cost_usdc=planned, actual_cost_usdc=Decimal("0.000000"), skip_reason=reason)
    try:
        session.add(run); session.flush()
    except IntegrityError:
        session.rollback()
        return session.query(AutonomyRun).filter_by(idempotency_key=key).one()
    policy.last_run_at = instant
    policy.next_run_at = slot + timedelta(seconds=policy.cadence_seconds)
    _event(session, run, "AUTONOMY_RUN_SKIPPED" if reason else "AUTONOMY_RUN_SCHEDULED")
    return run


def claim_run(session, run_id: str) -> AutonomyRun | None:
    run = session.query(AutonomyRun).filter_by(run_id=run_id, state="SCHEDULED").with_for_update(skip_locked=True).one_or_none()
    if run is None:
        return None
    run.state = "CLAIMED"; run.started_at = now(); _event(session, run, "AUTONOMY_RUN_STARTED")
    return run


def execute_claimed(session, run: AutonomyRun) -> str:
    policy = session.get(AutonomyPolicy, run.policy_id)
    if policy is None:
        run.state = "FAILED"; run.failure_code = "POLICY_MISSING"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    if policy.acquisition_mode == "TELEGRAPH_HTTP":
        if not global_enabled() or not policy.enabled or policy.state != "ACTIVE":
            run.state = "FAILED"; run.failure_code = "AUTONOMY_DISABLED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        if not policy.allow_telegraph_http or policy.read_only_replay:
            run.state = "FAILED"; run.failure_code = "HTTP_RAIL_NOT_ALLOWED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        if run.mandate_id:
            return "ALREADY_EXECUTED"
        instruction = policy.mandate_template.get("instruction")
        title = policy.mandate_template.get("title", "Autonomous PRAMA mandate")
        if not isinstance(instruction, str) or not instruction.strip() or not isinstance(title, str):
            run.state = "FAILED"; run.failure_code = "MANDATE_TEMPLATE_INVALID"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
        mandate = Mandate(
            actor_id="autonomy-controller", agent_id="autonomy-controller", client_id="prama-internal",
            text=instruction.strip(), mandate_type="AUTONOMOUS",
            constraints={"title": title, "autonomy_policy_id": policy.policy_id, "autonomy_run_id": run.run_id},
            max_budget_usdc=Decimal(run.planned_cost_usdc), status=MandateStatus.RECEIVED.value,
            origin="AUTONOMOUS", autonomy_policy_id=policy.policy_id, autonomy_run_id=run.run_id,
        )
        session.add(mandate); session.flush()
        # Bounded paid autonomy shares the G12 global daily reservation ledger.
        # Legacy over-budget policies may still be observed in the scheduler,
        # but the worker will fail them closed before any Gateway request.
        if Decimal(run.planned_cost_usdc) <= M2M_MAX_WORKFLOW_USDC:
            try:
                reserve_autonomous_spend(session, mandate.mandate_id, Decimal(run.planned_cost_usdc))
            except Exception as error:
                code = getattr(error, "detail", str(error))
                mandate.status = MandateStatus.FAILED.value
                session.add(MandateTransition(mandate_id=mandate.mandate_id, from_status=MandateStatus.RECEIVED.value, to_status=MandateStatus.FAILED.value, reason=str(code)[:255]))
                run.state = "FAILED"; run.failure_code = str(code)[:100]; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
                return run.state
        acquisition = AcquisitionTask(
            mandate_id=mandate.mandate_id, query=mandate.text, required=True,
            status=AcquisitionStatus.QUEUED.value, ordinal=0,
        )
        session.add(acquisition); session.flush()
        session.add_all([
            MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="autonomy scheduler due slot"),
            UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_={"autonomy_run_id": run.run_id, "autonomy_policy_id": policy.policy_id}),
            UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=acquisition.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_={"autonomy_run_id": run.run_id}),
        ])
        run.mandate_id = mandate.mandate_id; run.state = "RUNNING"; run.skip_reason = None
        return "ACQUISITION_QUEUED"
    if policy.acquisition_mode != "REPLAY_ONLY" or not policy.read_only_replay:
        run.state = "WAITING_EXTERNAL"; run.skip_reason = "PAID_RAIL_DISABLED"; return run.state
    source_id = policy.mandate_template.get("erc8183_job_id")
    if not isinstance(source_id, str):
        run.state = "FAILED"; run.failure_code = "REPLAY_SOURCE_MISSING"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    try:
        replay = replay_persisted(session, source_id)
    except Exception:
        run.state = "FAILED"; run.failure_code = "REPLAY_FAILED"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    if not replay["matches"]:
        run.state = "FAILED"; run.failure_code = "REPLAY_MISMATCH"; run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_FAILED"); return run.state
    source = session.get(ERC8183Job, source_id)
    run.state = "COMPLETED"; run.mandate_id = source.mandate_id; run.erc8183_job_id = source_id; run.ticket_id = source.ticket_id; run.actual_cost_usdc = Decimal("0.000000"); run.finished_at = now(); _event(session, run, "AUTONOMY_RUN_COMPLETED")
    return run.state


def _actual_cost(session, mandate_id: str) -> Decimal:
    return sum((Decimal(call.cost_usd or 0) for call in session.query(TelegraphCall).filter_by(mandate_id=mandate_id, status="SUCCEEDED")), Decimal("0.000000"))


def finalize_http_run(session, mandate_id: str, *, failure_code: str | None = None) -> str | None:
    """Close the exact run that originated this autonomous mandate.

    This function is called only after the existing pipeline reaches a durable
    terminal state; it never sends a request, payment, or chain transaction.
    """
    run = session.query(AutonomyRun).filter_by(mandate_id=mandate_id).one_or_none()
    if run is None or run.state in {"COMPLETED", "FAILED", "SKIPPED"}:
        return run.state if run else None
    actual = _actual_cost(session, mandate_id)
    run.actual_cost_usdc = actual
    run.finished_at = now()
    if failure_code:
        run.state = "FAILED"; run.failure_code = failure_code[:100]; _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    mandate = session.get(Mandate, mandate_id)
    ticket = session.query(Ticket).filter_by(mandate_id=mandate_id).one_or_none()
    if mandate is None or mandate.status != MandateStatus.TICKETED.value or ticket is None:
        run.state = "FAILED"; run.failure_code = "AUTONOMY_PIPELINE_INCOMPLETE"; _event(session, run, "AUTONOMY_RUN_FAILED")
        return run.state
    run.ticket_id = ticket.ticket_id; run.state = "COMPLETED"; run.failure_code = None; _event(session, run, "AUTONOMY_RUN_COMPLETED")
    return run.state


def recover_runs(session) -> list[str]:
    recovered = []
    for run in session.query(AutonomyRun).filter(AutonomyRun.state.in_(["CLAIMED", "RUNNING"])).all():
        run.state = "SCHEDULED"; run.started_at = None; recovered.append(run.run_id)
    return recovered


def status(session, instant: datetime | None = None) -> dict:
    instant = instant or now(); start, end = _day_bounds(instant)
    policies = session.query(AutonomyPolicy).all()
    runs = session.query(AutonomyRun).all()
    today = [run for run in runs if start <= run.scheduled_for < end]
    active = [run for run in runs if run.state in ACTIVE_RUN_STATES]
    next_due = min((policy.next_run_at for policy in policies if policy.enabled and policy.next_run_at), default=None)
    return {"global_enabled": global_enabled(), "active_policy_count": sum(1 for policy in policies if policy.enabled and policy.state == "ACTIVE"), "active_run_count": len(active), "today_run_count": len(today), "today_spend_usdc": str(sum((Decimal(run.actual_cost_usdc) for run in today), Decimal("0"))), "next_due_at": next_due, "autonomous_runs_total": len(runs), "completed": sum(1 for run in runs if run.state == "COMPLETED"), "skipped": sum(1 for run in runs if run.state == "SKIPPED"), "failed": sum(1 for run in runs if run.state == "FAILED"), "actual_usdc_spend": str(sum((Decimal(run.actual_cost_usdc) for run in runs), Decimal("0")))}
