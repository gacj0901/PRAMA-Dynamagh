"""Deterministic autonomous-domain observations for G13-C.

O_AGENT is deliberately a read-only projection of persisted domain artifacts.
It records what happened locally and what was or was not persisted; it does
not decide whether a trajectory should continue.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AcquisitionTask,
    AgentIdentity,
    AutonomyPolicy,
    AutonomyRun,
    Decision,
    Evidence,
    Mandate,
    PublicManualSpendReservation,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.pramagraph.evaluation import canonical, digest


O_AGENT_SCHEMA_VERSION = "o-agent-v0"


class OAgentSourceLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_identity_id: str
    autonomy_policy_ids: tuple[str, ...] = ()
    autonomy_run_ids: tuple[str, ...] = ()
    mandate_ids: tuple[str, ...] = ()
    acquisition_ids: tuple[str, ...] = ()
    telegraph_call_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    evaluation_ids: tuple[str, ...] = ()
    decision_ids: tuple[str, ...] = ()
    ticket_ids: tuple[str, ...] = ()
    usage_event_ids: tuple[str, ...] = ()
    reservation_mandate_ids: tuple[str, ...] = ()


class OAgentFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_status: str | None = None
    mandate_status: str | None = None
    autonomy_run_state: str | None = None
    acquisition_statuses: tuple[str, ...] = ()
    telegraph_statuses: tuple[str, ...] = ()
    attempt_count: int | None = None
    latency_ms: int | None = None
    local_decision_state: str | None = None
    local_decision_scope: Literal["LOCAL_DECISION_ONLY"] | None = None
    trajectory_viability: None = None
    reserved_usdc: str | None = None
    incurred_usdc: str | None = None
    planned_usdc: str | None = None
    mandate_budget_usdc: str | None = None
    telegraph_cost_usd: str | None = None
    max_usdc_per_run: str | None = None
    max_usdc_per_day: str | None = None
    budget_pressure_ratio: str | None = None
    concurrency_limit: int | None = None
    active_run_count: int | None = None
    cadence_seconds: int | None = None
    prior_run_count: int | None = None
    prior_mandate_count: int | None = None
    failure_code: str | None = None
    failure_event_types: tuple[str, ...] = ()
    recovery_event_types: tuple[str, ...] = ()
    recovered: bool | None = None
    evidence_complete: bool = False
    evaluation_complete: bool = False
    decision_complete: bool = False
    ticket_complete: bool = False


class OAgentObservation(BaseModel):
    """One immutable, versioned observation of a persisted source artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["o-agent-v0"] = O_AGENT_SCHEMA_VERSION
    observation_id: str
    sequence: int = Field(ge=1)
    observed_at: str | None = None
    timestamp_source: str | None = None
    agent_identity_id: str
    agent_origin: str
    origin_surface: Literal["M2M", "AUTONOMOUS", "OTHER"]
    source_kind: str
    source_id: str
    source_lineage: OAgentSourceLineage
    facts: OAgentFacts
    missing_data: tuple[str, ...] = ()
    content_hash: str

    def canonical_payload(self) -> dict[str, Any]:
        """Return the exact JSON-safe payload covered by ``content_hash``."""

        return self.model_dump(mode="json", exclude={"content_hash"})

    def canonical_bytes(self) -> bytes:
        return canonical(self.canonical_payload())


class _Artifact:
    def __init__(
        self,
        *,
        source_kind: str,
        source_id: str,
        observed_at: datetime | None,
        timestamp_source: str | None,
        facts: OAgentFacts,
        lineage: OAgentSourceLineage,
        missing_data: tuple[str, ...],
    ) -> None:
        self.source_kind = source_kind
        self.source_id = source_id
        self.observed_at = observed_at
        self.timestamp_source = timestamp_source
        self.facts = facts
        self.lineage = lineage
        self.missing_data = missing_data


def _surface(identity: AgentIdentity) -> Literal["M2M", "AUTONOMOUS", "OTHER"]:
    if identity.origin == "EXTERNAL_API_AGENT":
        return "M2M"
    if identity.origin == "INTERNAL_AUTONOMY":
        return "AUTONOMOUS"
    return "OTHER"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decimal(value: Decimal | int | float | str | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)):.6f}"


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return f"{(numerator / denominator):.12f}"


def _latest(items: list[Any]) -> Any | None:
    if not items:
        return None
    return sorted(items, key=lambda item: (_iso(getattr(item, "created_at", None)) or "", str(getattr(item, "evaluation_id", getattr(item, "decision_id", getattr(item, "ticket_id", ""))))), reverse=True)[0]


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _latency_ms(task: AcquisitionTask | None, call: TelegraphCall | None) -> int | None:
    if call is not None and call.duration_ms is not None:
        return call.duration_ms
    if task is not None and task.started_at is not None and task.completed_at is not None:
        delta = (task.completed_at - task.started_at).total_seconds() * 1000
        if delta >= 0:
            return int(delta)
    return None


def _lineage(
    identity_id: str,
    *,
    policies: list[AutonomyPolicy],
    runs: list[AutonomyRun],
    mandates: list[Mandate],
    tasks: list[AcquisitionTask],
    calls: list[TelegraphCall],
    evidence: list[Evidence],
    evaluations: list[StructuralEvaluation],
    decisions: list[Decision],
    tickets: list[Ticket],
    events: list[UsageEvent],
    reservations: list[PublicManualSpendReservation],
) -> OAgentSourceLineage:
    return OAgentSourceLineage(
        agent_identity_id=identity_id,
        autonomy_policy_ids=_unique([item.policy_id for item in policies]),
        autonomy_run_ids=_unique([item.run_id for item in runs]),
        mandate_ids=_unique([item.mandate_id for item in mandates]),
        acquisition_ids=_unique([item.acquisition_id for item in tasks]),
        telegraph_call_ids=_unique([item.telegraph_call_id for item in calls]),
        evidence_ids=_unique([item.evidence_id for item in evidence]),
        evaluation_ids=_unique([item.evaluation_id for item in evaluations]),
        decision_ids=_unique([item.decision_id for item in decisions]),
        ticket_ids=_unique([item.ticket_id for item in tickets]),
        usage_event_ids=_unique([item.event_id for item in events]),
        reservation_mandate_ids=_unique([item.mandate_id for item in reservations]),
    )


def _facts(
    *,
    action_status: str | None,
    mandate: Mandate | None,
    run: AutonomyRun | None,
    policy: AutonomyPolicy | None,
    tasks: list[AcquisitionTask],
    calls: list[TelegraphCall],
    reservation: PublicManualSpendReservation | None,
    decision: Decision | None,
    evidence: list[Evidence],
    evaluation: StructuralEvaluation | None,
    ticket: Ticket | None,
    events: list[UsageEvent],
    prior_run_count: int | None,
    prior_mandate_count: int | None,
    active_run_count: int | None,
    recovered_override: bool | None = None,
) -> OAgentFacts:
    statuses = [item.status for item in tasks]
    call_statuses = [item.status for item in calls]
    task_attempts = [item.attempt_count for item in tasks if item.attempt_count is not None]
    call_cost = sum((Decimal(str(item.cost_usd)) for item in calls if item.cost_usd is not None), Decimal("0"))
    reserved = reservation.reserved_usdc if reservation is not None else None
    incurred = reservation.actual_spend_usdc if reservation is not None else None
    if incurred is None and run is not None:
        incurred = run.actual_cost_usdc
    planned = run.planned_cost_usdc if run is not None else None
    failure_events = sorted({item.event_type for item in events if "FAIL" in item.event_type})
    recovery_events = sorted({item.event_type for item in events if "COMPLET" in item.event_type or "RECOVER" in item.event_type})
    has_failure = bool(failure_events) or bool(run and run.failure_code)
    recovered = recovered_override if recovered_override is not None else (bool(recovery_events) if has_failure else None)
    mandate_budget = mandate.max_budget_usdc if mandate is not None else None
    daily_cap = policy.max_usdc_per_day if policy is not None else None
    return OAgentFacts(
        action_status=action_status,
        mandate_status=mandate.status if mandate is not None else None,
        autonomy_run_state=run.state if run is not None else None,
        acquisition_statuses=tuple(statuses),
        telegraph_statuses=tuple(call_statuses),
        attempt_count=max(task_attempts) if task_attempts else None,
        latency_ms=_latency_ms(tasks[0] if tasks else None, calls[0] if calls else None),
        local_decision_state=decision.state if decision is not None else None,
        local_decision_scope="LOCAL_DECISION_ONLY" if decision is not None else None,
        reserved_usdc=_decimal(reserved),
        incurred_usdc=_decimal(incurred),
        planned_usdc=_decimal(planned),
        mandate_budget_usdc=_decimal(mandate_budget),
        telegraph_cost_usd=_decimal(call_cost if calls else None),
        max_usdc_per_run=_decimal(policy.max_usdc_per_run if policy is not None else None),
        max_usdc_per_day=_decimal(daily_cap),
        budget_pressure_ratio=_ratio(reserved, daily_cap),
        concurrency_limit=policy.max_concurrent_runs if policy is not None else None,
        active_run_count=active_run_count,
        cadence_seconds=policy.cadence_seconds if policy is not None else None,
        prior_run_count=prior_run_count,
        prior_mandate_count=prior_mandate_count,
        failure_code=run.failure_code if run is not None and run.failure_code else None,
        failure_event_types=tuple(failure_events),
        recovery_event_types=tuple(recovery_events),
        recovered=recovered,
        evidence_complete=bool(evidence),
        evaluation_complete=evaluation is not None,
        decision_complete=decision is not None,
        ticket_complete=ticket is not None,
    )


def _missing(
    *,
    observed_at: datetime | None,
    mandate: Mandate | None,
    run: AutonomyRun | None,
    policy: AutonomyPolicy | None,
    tasks: list[AcquisitionTask],
    calls: list[TelegraphCall],
    reservation: PublicManualSpendReservation | None,
    decision: Decision | None,
    evidence: list[Evidence],
    evaluation: StructuralEvaluation | None,
    ticket: Ticket | None,
    active_run_count: int | None,
) -> tuple[str, ...]:
    missing: list[str] = []
    if observed_at is None:
        missing.append("TIMESTAMP_NOT_AVAILABLE")
    if mandate is None:
        missing.append("MANDATE_NOT_LINKED")
    if run is None:
        missing.append("AUTONOMY_RUN_NOT_LINKED")
    if policy is None:
        missing.append("AUTONOMY_POLICY_NOT_LINKED")
    if not tasks:
        missing.append("ACQUISITION_NOT_PRESENT")
    if not calls:
        missing.append("TELEGRAPH_CALL_NOT_PRESENT")
    elif all(item.duration_ms is None for item in calls):
        missing.append("TELEGRAPH_LATENCY_NOT_AVAILABLE")
    if reservation is None:
        missing.append("SPEND_RESERVATION_NOT_PRESENT")
    if not evidence:
        missing.append("EVIDENCE_NOT_PRESENT")
    if evaluation is None:
        missing.append("EVALUATION_NOT_PRESENT")
    if decision is None:
        missing.append("LOCAL_DECISION_NOT_PRESENT")
    if ticket is None:
        missing.append("TICKET_NOT_PRESENT")
    if run is not None and active_run_count is None:
        missing.append("CONCURRENCY_NOT_DERIVABLE")
    return tuple(missing)


def _artifact(
    *,
    identity_id: str,
    source_kind: str,
    source_id: str,
    observed_at: datetime | None,
    timestamp_source: str | None,
    surface: Literal["M2M", "AUTONOMOUS", "OTHER"],
    agent_origin: str,
    lineage: OAgentSourceLineage,
    facts: OAgentFacts,
    missing_data: tuple[str, ...],
) -> _Artifact:
    return _Artifact(
        source_kind=source_kind,
        source_id=source_id,
        observed_at=observed_at,
        timestamp_source=timestamp_source,
        facts=facts,
        lineage=lineage,
        missing_data=missing_data,
    )


def _in_interval(value: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if value is None:
        return start is None and end is None
    return (start is None or value >= start) and (end is None or value < end)


def build_o_agent_stream(
    session: Session,
    agent_identity_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    run_id: str | None = None,
) -> list[OAgentObservation]:
    """Build an ordered O_AGENT stream scoped to exactly one AgentIdentity.

    The function only reads persisted rows.  A supplied ``run_id`` must belong
    to the requested identity; this prevents a caller from using a run handle
    to pull another agent's artifacts.
    """

    identity = session.get(AgentIdentity, agent_identity_id)
    if identity is None:
        raise ValueError("AGENT_IDENTITY_MISSING")

    all_runs = list(session.query(AutonomyRun).filter(AutonomyRun.agent_identity_id == agent_identity_id).all())
    if run_id is not None:
        requested = session.get(AutonomyRun, run_id)
        if requested is None:
            raise ValueError("AUTONOMY_RUN_MISSING")
        if requested.agent_identity_id != agent_identity_id:
            raise ValueError("AGENT_RUN_SCOPE_MISMATCH")
        runs = [requested]
    else:
        runs = all_runs

    mandates = list(session.query(Mandate).filter(Mandate.agent_identity_id == agent_identity_id).all())
    if run_id is not None:
        mandates = [item for item in mandates if item.mandate_id == runs[0].mandate_id]
    mandate_ids = {item.mandate_id for item in mandates}
    run_mandates = {item.mandate_id for item in runs if item.mandate_id in mandate_ids}
    mandate_ids.update(run_mandates)

    tasks = list(session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    calls = list(session.query(TelegraphCall).filter(TelegraphCall.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    evidence = list(session.query(Evidence).filter(Evidence.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    evaluations = list(session.query(StructuralEvaluation).filter(StructuralEvaluation.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    decisions = list(session.query(Decision).filter(Decision.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    tickets = list(session.query(Ticket).filter(Ticket.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []
    reservations = list(session.query(PublicManualSpendReservation).filter(PublicManualSpendReservation.mandate_id.in_(mandate_ids)).all()) if mandate_ids else []

    events = []
    for event in session.query(UsageEvent).all():
        metadata_identity = (event.metadata_ or {}).get("agent_identity_id")
        if event.mandate_id in mandate_ids:
            if metadata_identity not in (None, agent_identity_id):
                continue
            events.append(event)
        elif event.mandate_id is None and metadata_identity == agent_identity_id:
            events.append(event)

    policy_ids = {item.policy_id for item in runs}
    policy_ids.update(item.autonomy_policy_id for item in mandates if item.autonomy_policy_id)
    policies = list(session.query(AutonomyPolicy).filter(AutonomyPolicy.policy_id.in_(policy_ids)).all()) if policy_ids else []
    policy_by_id = {item.policy_id: item for item in policies}
    mandate_by_id = {item.mandate_id: item for item in mandates}
    runs_by_mandate: dict[str, list[AutonomyRun]] = {}
    for item in all_runs:
        if item.mandate_id in mandate_ids:
            runs_by_mandate.setdefault(item.mandate_id, []).append(item)
    tasks_by_mandate: dict[str, list[AcquisitionTask]] = {}
    for item in tasks:
        tasks_by_mandate.setdefault(item.mandate_id, []).append(item)
    calls_by_mandate: dict[str, list[TelegraphCall]] = {}
    for item in calls:
        calls_by_mandate.setdefault(item.mandate_id, []).append(item)
    evidence_by_mandate: dict[str, list[Evidence]] = {}
    for item in evidence:
        evidence_by_mandate.setdefault(item.mandate_id, []).append(item)
    evaluations_by_mandate: dict[str, list[StructuralEvaluation]] = {}
    for item in evaluations:
        evaluations_by_mandate.setdefault(item.mandate_id, []).append(item)
    decisions_by_mandate: dict[str, list[Decision]] = {}
    for item in decisions:
        decisions_by_mandate.setdefault(item.mandate_id, []).append(item)
    tickets_by_mandate: dict[str, list[Ticket]] = {}
    for item in tickets:
        tickets_by_mandate.setdefault(item.mandate_id, []).append(item)
    reservations_by_mandate = {item.mandate_id: item for item in reservations}
    events_by_mandate: dict[str, list[UsageEvent]] = {}
    events_by_run: dict[str, list[UsageEvent]] = {}
    for item in events:
        if item.mandate_id is not None:
            events_by_mandate.setdefault(item.mandate_id, []).append(item)
        event_run_id = (item.metadata_ or {}).get("autonomy_run_id")
        if event_run_id:
            events_by_run.setdefault(event_run_id, []).append(item)

    def context_for(mandate_id: str | None, run: AutonomyRun | None) -> dict[str, Any]:
        mandate = mandate_by_id.get(mandate_id) if mandate_id else None
        related_runs = runs_by_mandate.get(mandate_id or "", [])
        selected_run = run or (_latest(related_runs) if related_runs else None)
        policy_id = selected_run.policy_id if selected_run is not None else (mandate.autonomy_policy_id if mandate else None)
        policy = policy_by_id.get(policy_id) if policy_id else None
        selected_tasks = tasks_by_mandate.get(mandate_id or "", [])
        selected_calls = calls_by_mandate.get(mandate_id or "", [])
        selected_evidence = evidence_by_mandate.get(mandate_id or "", [])
        selected_evaluations = evaluations_by_mandate.get(mandate_id or "", [])
        selected_decisions = decisions_by_mandate.get(mandate_id or "", [])
        selected_tickets = tickets_by_mandate.get(mandate_id or "", [])
        selected_events = list(events_by_mandate.get(mandate_id or "", []))
        if selected_run is not None:
            selected_events.extend(events_by_run.get(selected_run.run_id, []))
        selected_events = sorted({item.event_id: item for item in selected_events}.values(), key=lambda item: (item.created_at, item.event_id))
        reservation = reservations_by_mandate.get(mandate_id or "")
        active_count = None
        if selected_run is not None and selected_run.started_at is not None:
            at = selected_run.started_at
            active_count = sum(
                1
                for candidate in all_runs
                if candidate.policy_id == selected_run.policy_id
                and candidate.started_at is not None
                and candidate.started_at <= at
                and (candidate.finished_at is None or candidate.finished_at > at)
            )
        prior_run_count = None
        if selected_run is not None:
            prior_run_count = sum(1 for candidate in all_runs if candidate.scheduled_for < selected_run.scheduled_for)
        prior_mandate_count = None
        if mandate is not None:
            prior_mandate_count = sum(1 for candidate in mandates if candidate.created_at < mandate.created_at)
        latest_decision = _latest(selected_decisions)
        latest_evaluation = _latest(selected_evaluations)
        latest_ticket = _latest(selected_tickets)
        recovered_override = None
        if selected_run is not None and selected_run.state == "COMPLETED":
            recovered_override = any(
                candidate.state == "FAILED" and candidate.scheduled_for < selected_run.scheduled_for
                for candidate in all_runs
            )
        return {
            "mandate": mandate,
            "run": selected_run,
            "policy": policy,
            "tasks": sorted(selected_tasks, key=lambda item: (item.ordinal, item.acquisition_id)),
            "calls": sorted(selected_calls, key=lambda item: item.telegraph_call_id),
            "evidence": sorted(selected_evidence, key=lambda item: item.evidence_id),
            "evaluation": latest_evaluation,
            "decision": latest_decision,
            "ticket": latest_ticket,
            "reservation": reservation,
            "events": selected_events,
            "active_count": active_count,
            "prior_run_count": prior_run_count,
            "prior_mandate_count": prior_mandate_count,
            "recovered_override": recovered_override,
        }

    artifacts: list[_Artifact] = []
    identity_lineage = _lineage(
        agent_identity_id,
        policies=[], runs=[], mandates=[], tasks=[], calls=[], evidence=[], evaluations=[], decisions=[], tickets=[], events=[], reservations=[],
    )
    identity_observed_at = identity.created_at
    identity_missing = ("MANDATE_NOT_LINKED", "AUTONOMY_RUN_NOT_LINKED", "AUTONOMY_POLICY_NOT_LINKED", "ACQUISITION_NOT_PRESENT", "TELEGRAPH_CALL_NOT_PRESENT", "SPEND_RESERVATION_NOT_PRESENT", "EVIDENCE_NOT_PRESENT", "EVALUATION_NOT_PRESENT", "LOCAL_DECISION_NOT_PRESENT", "TICKET_NOT_PRESENT")
    identity_facts = OAgentFacts(action_status=identity.status)
    artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="AGENT_IDENTITY", source_id=identity.agent_id, observed_at=identity_observed_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=identity_lineage, facts=identity_facts, missing_data=identity_missing))

    # Recovery transitions are global, agent-attributed UsageEvents. Include
    # them in O_AGENT without attaching them to a synthetic mandate or run.
    for event in events:
        if event.mandate_id is not None or event.event_type != "G13_RECOVERY_EVENT":
            continue
        event_lineage = _lineage(
            agent_identity_id,
            policies=[], runs=[], mandates=[], tasks=[], calls=[], evidence=[], evaluations=[], decisions=[], tickets=[],
            events=[event], reservations=[],
        )
        artifacts.append(_artifact(
            identity_id=agent_identity_id,
            source_kind="USAGE_EVENT",
            source_id=event.event_id,
            observed_at=event.created_at,
            timestamp_source="created_at",
            surface=_surface(identity),
            agent_origin=identity.origin,
            lineage=event_lineage,
            facts=OAgentFacts(action_status=event.event_type, recovery_event_types=(event.event_type,)),
            missing_data=identity_missing,
        ))

    for run in runs:
        context = context_for(run.mandate_id, run)
        mandate = context["mandate"]
        source_time = run.started_at or run.scheduled_for or run.created_at
        source_name = "started_at" if run.started_at is not None else "scheduled_for"
        lineage = _lineage(agent_identity_id, policies=[context["policy"]] if context["policy"] else [], runs=[run], mandates=[mandate] if mandate else [], tasks=context["tasks"], calls=context["calls"], evidence=context["evidence"], evaluations=[context["evaluation"]] if context["evaluation"] else [], decisions=[context["decision"]] if context["decision"] else [], tickets=[context["ticket"]] if context["ticket"] else [], events=context["events"], reservations=[context["reservation"]] if context["reservation"] else [])
        facts = _facts(action_status=run.state, mandate=mandate, run=run, policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"], recovered_override=context["recovered_override"])
        missing = _missing(observed_at=source_time, mandate=mandate, run=run, policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
        artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="AUTONOMY_RUN", source_id=run.run_id, observed_at=source_time, timestamp_source=source_name, surface=_surface(identity), agent_origin=identity.origin, lineage=lineage, facts=facts, missing_data=missing))

    def add_mandate_artifacts(mandate: Mandate) -> None:
        context = context_for(mandate.mandate_id, None)
        lineage_base = dict(
            policies=[context["policy"]] if context["policy"] else [], runs=[context["run"]] if context["run"] else [], mandates=[mandate], tasks=context["tasks"], calls=context["calls"], evidence=context["evidence"], evaluations=[context["evaluation"]] if context["evaluation"] else [], decisions=[context["decision"]] if context["decision"] else [], tickets=[context["ticket"]] if context["ticket"] else [], events=context["events"], reservations=[context["reservation"]] if context["reservation"] else [],
        )
        lineage = _lineage(agent_identity_id, **lineage_base)
        facts = _facts(action_status=mandate.status, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
        missing = _missing(observed_at=mandate.created_at, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
        artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="MANDATE", source_id=mandate.mandate_id, observed_at=mandate.created_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=lineage, facts=facts, missing_data=missing))
        for task in context["tasks"]:
            call = next((item for item in context["calls"] if item.acquisition_id == task.acquisition_id), None)
            task_lineage = _lineage(agent_identity_id, **{**lineage_base, "tasks": [task], "calls": [call] if call else []})
            task_facts = _facts(action_status=task.status, mandate=mandate, run=context["run"], policy=context["policy"], tasks=[task], calls=[call] if call else [], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
            task_missing = _missing(observed_at=task.created_at, mandate=mandate, run=context["run"], policy=context["policy"], tasks=[task], calls=[call] if call else [], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
            artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="ACQUISITION_TASK", source_id=task.acquisition_id, observed_at=task.created_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=task_lineage, facts=task_facts, missing_data=task_missing))
            if call is not None:
                call_lineage = _lineage(agent_identity_id, **{**lineage_base, "tasks": [task], "calls": [call]})
                call_facts = _facts(action_status=call.status, mandate=mandate, run=context["run"], policy=context["policy"], tasks=[task], calls=[call], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
                call_missing = _missing(observed_at=call.created_at, mandate=mandate, run=context["run"], policy=context["policy"], tasks=[task], calls=[call], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
                artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="TELEGRAPH_CALL", source_id=call.telegraph_call_id, observed_at=call.created_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=call_lineage, facts=call_facts, missing_data=call_missing))
        derived_items = [(item, "EVIDENCE", item.created_at, "created_at") for item in context["evidence"]]
        if context["evaluation"] is not None:
            derived_items.append((context["evaluation"], "EVALUATION", context["evaluation"].created_at, "created_at"))
        if context["decision"] is not None:
            derived_items.append((context["decision"], "DECISION", context["decision"].created_at, "created_at"))
        if context["ticket"] is not None:
            derived_items.append((context["ticket"], "TICKET", context["ticket"].created_at, "created_at"))
        for item, kind, source_time, source_name in derived_items:
            item_lineage = lineage
            item_facts = _facts(action_status=getattr(item, "state", None), mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
            item_missing = _missing(observed_at=source_time, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
            item_id = getattr(item, "evidence_id", getattr(item, "evaluation_id", getattr(item, "decision_id", getattr(item, "ticket_id", ""))))
            artifacts.append(_artifact(identity_id=agent_identity_id, source_kind=kind, source_id=item_id, observed_at=source_time, timestamp_source=source_name, surface=_surface(identity), agent_origin=identity.origin, lineage=item_lineage, facts=item_facts, missing_data=item_missing))
        if context["reservation"] is not None:
            reservation = context["reservation"]
            reservation_lineage = lineage
            reservation_facts = _facts(action_status=reservation.status, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=reservation, decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=context["events"], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
            reservation_missing = _missing(observed_at=reservation.created_at, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=reservation, decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
            artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="SPEND_RESERVATION", source_id=reservation.mandate_id, observed_at=reservation.created_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=reservation_lineage, facts=reservation_facts, missing_data=reservation_missing))
        for event in context["events"]:
            event_lineage = _lineage(agent_identity_id, **{**lineage_base, "events": [event]})
            event_facts = _facts(action_status=event.event_type, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], events=[event], prior_run_count=context["prior_run_count"], prior_mandate_count=context["prior_mandate_count"], active_run_count=context["active_count"])
            event_missing = _missing(observed_at=event.created_at, mandate=mandate, run=context["run"], policy=context["policy"], tasks=context["tasks"], calls=context["calls"], reservation=context["reservation"], decision=context["decision"], evidence=context["evidence"], evaluation=context["evaluation"], ticket=context["ticket"], active_run_count=context["active_count"])
            artifacts.append(_artifact(identity_id=agent_identity_id, source_kind="USAGE_EVENT", source_id=event.event_id, observed_at=event.created_at, timestamp_source="created_at", surface=_surface(identity), agent_origin=identity.origin, lineage=event_lineage, facts=event_facts, missing_data=event_missing))

    for mandate in sorted(mandates, key=lambda item: (item.created_at, item.mandate_id)):
        add_mandate_artifacts(mandate)

    filtered = [item for item in artifacts if _in_interval(item.observed_at, start, end)]
    source_order = {"AGENT_IDENTITY": 0, "AUTONOMY_RUN": 1, "MANDATE": 2, "ACQUISITION_TASK": 3, "TELEGRAPH_CALL": 4, "EVIDENCE": 5, "EVALUATION": 6, "DECISION": 7, "TICKET": 8, "SPEND_RESERVATION": 9, "USAGE_EVENT": 10}
    filtered.sort(key=lambda item: (_iso(item.observed_at) or "\uffff", source_order.get(item.source_kind, 99), item.source_id))

    observations: list[OAgentObservation] = []
    for sequence, item in enumerate(filtered, start=1):
        payload = {
            "schema_version": O_AGENT_SCHEMA_VERSION,
            "observation_id": f"{O_AGENT_SCHEMA_VERSION}:{item.source_kind}:{item.source_id}",
            "sequence": sequence,
            "observed_at": _iso(item.observed_at),
            "timestamp_source": item.timestamp_source,
            "agent_identity_id": agent_identity_id,
            "agent_origin": identity.origin,
            "origin_surface": _surface(identity),
            "source_kind": item.source_kind,
            "source_id": item.source_id,
            "source_lineage": item.lineage.model_dump(mode="json"),
            "facts": item.facts.model_dump(mode="json"),
            "missing_data": list(item.missing_data),
        }
        observations.append(OAgentObservation(**payload, content_hash=digest(payload)))
    return observations


def build_observation_stream(*args: Any, **kwargs: Any) -> list[OAgentObservation]:
    """Compatibility alias for callers that do not need the O_AGENT name."""

    return build_o_agent_stream(*args, **kwargs)


def build_o_agent_disclosure(session: Session, agent_identity_id: str, *, as_of: datetime) -> dict:
    """Additive O_AGENT dimension; preserve the frozen o-agent-v0 fact schema."""
    from app.agents.disclosure_memory import build_disclosure_memory
    if session.get(AgentIdentity, agent_identity_id) is None:
        raise ValueError("AGENT_IDENTITY_MISSING")
    return {
        "observer": "O_AGENT", "dimension": "DISCLOSURE_COMPLIANCE",
        "agent_identity_id": agent_identity_id,
        "memory": build_disclosure_memory(session, agent_identity_id, as_of=as_of),
        "decision_gate_integration": "NONE", "g13_enforcement": "UNCHANGED",
    }
