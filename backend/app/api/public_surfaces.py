"""Small, read-only public surfaces for real Track 3 workflows.

These endpoints expose aggregates plus a bounded allowlisted execution-history
projection with short request previews and persisted Evidence hashes. They do
not return owner-scoped USER artifacts, Evidence payloads, provider responses,
signer material, payment identities, result capabilities, or mutation access.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.mandates import (
    AcquisitionTask,
    AutonomyRun,
    Decision,
    Evidence,
    InboundX402Payment,
    Mandate,
    AutonomyPolicy,
    PolicyEvaluation,
    PublicManualSpendReservation,
    StructuralEvaluation,
    TelegraphCall,
    Ticket,
    UsageEvent,
)
from app.competition import competition_budget_profile
from app.persistence.database import get_session


router = APIRouter(tags=["public-read-surfaces"])
PUBLIC_ORIGINS = ("MANUAL", "M2M", "USER")
FIXTURE_POLICY_NAMES = frozenset({
    "G10 Live Autonomous Telegraph Fixture",
    "G10 Replay-Only Verification Fixture",
    "G10 Autonomous Fixture",
    "prama-bounded-telegraph-http-v1",
})


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Decimal | None) -> str:
    return f"{Decimal(value or 0):.6f}"


def _processed_call(call: TelegraphCall) -> bool:
    """A Miner response is a completed call with provider identity and signal."""
    return (
        getattr(call, "status", None) == "SUCCEEDED"
        and bool(getattr(call, "miner_id", None))
        and bool(getattr(call, "signal_hash", None))
    )


def _activity_read_model(
    session: Session,
    mandates: list[Mandate],
    calls: list[TelegraphCall],
    evidence: list[Evidence],
) -> dict[str, Any]:
    """Return semantic production metrics from persisted response lineage.

    ``telegraph_calls`` remains available as a transport metric.  The public
    activity surface uses ``processed_responses`` for Miner work so a request
    that never yielded a Miner signal cannot be presented as processed work.
    """
    processed = [item for item in calls if _processed_call(item)]
    evidence_call_ids = {
        str(item.telegraph_call_id)
        for item in evidence
        if getattr(item, "telegraph_call_id", None)
    }
    evidence_acquisition_ids = {
        str(item.acquisition_id)
        for item in evidence
        if getattr(item, "acquisition_id", None)
    }
    with_evidence = [
        item for item in processed
        if str(item.telegraph_call_id) in evidence_call_ids
        or str(item.acquisition_id) in evidence_acquisition_ids
    ]
    by_intent = Counter(str(getattr(item, "intent", None)) for item in processed if getattr(item, "intent", None))
    latest = max(
        processed,
        key=lambda item: (getattr(item, "created_at", None) or 0, str(getattr(item, "telegraph_call_id", ""))),
        default=None,
    )
    mandate_by_id = {item.mandate_id: item for item in mandates}
    reservations: dict[str, PublicManualSpendReservation] = {}
    if mandates:
        reservations = {
            str(item.mandate_id): item
            for item in session.query(PublicManualSpendReservation)
            .filter(PublicManualSpendReservation.mandate_id.in_(list(mandate_by_id)))
            .all()
        }
    actual_spend = sum(
        (Decimal(getattr(item, "actual_spend_usdc", 0) or 0) for item in reservations.values()),
        Decimal("0"),
    )
    latest_response = None
    if latest is not None:
        reservation = reservations.get(str(latest.mandate_id))
        if reservation is None:
            economic_state = "UNAVAILABLE"
        elif str(getattr(reservation, "status", "")) == "SETTLED":
            economic_state = "PAYMENT_CONFIRMED"
        elif str(getattr(reservation, "status", "")) == "RELEASED":
            economic_state = "RECONCILED_NO_PAYMENT"
        elif str(getattr(reservation, "status", "")) == "RESERVED":
            economic_state = "PAYMENT_UNCERTAIN"
        else:
            economic_state = "UNAVAILABLE"
        latest_response = {
            "telegraph_call_id": getattr(latest, "telegraph_call_id", None),
            "mandate_id": getattr(latest, "mandate_id", None),
            "origin": getattr(mandate_by_id.get(getattr(latest, "mandate_id", None)), "origin", None),
            "intent": getattr(latest, "intent", None),
            "miner_id": getattr(latest, "miner_id", None),
            "miner_name": getattr(latest, "miner_name", None),
            "signal_hash": getattr(latest, "signal_hash", None),
            "cost_usdc": _money(getattr(latest, "cost_usd", None)),
            "duration_ms": getattr(latest, "duration_ms", None),
            "economic_state": economic_state,
            "with_evidence": latest in with_evidence,
        }
    return {
        "processed_responses": len(processed),
        "responses_with_evidence": len(with_evidence),
        "unique_miners_processed": sorted({str(item.miner_id) for item in processed if item.miner_id}),
        "responses_by_intent": dict(sorted(by_intent.items())),
        "actual_spend_usdc": _money(actual_spend),
        "latest_miner_response": latest_response,
    }


def _execution_history(session: Session, mandates: list[Mandate], *, limit: int = 25) -> list[dict[str, Any]]:
    """Project a small allowlisted history for the public operator surface.

    USER-origin artifacts are owner-scoped by ``protect_user_artifact`` and
    must not be copied into an unscoped list endpoint. Their aggregate counts
    remain available under USER as a distinct origin.
    This projection never includes Evidence.normalized_payload, provider
    responses, payment identities, or result-capability material. Server
    delivery is inferred only from persisted server delivery events.
    """
    visible_mandates = [item for item in mandates if getattr(item, "origin", None) != "USER"]
    mandate_by_id = {str(item.mandate_id): item for item in visible_mandates}
    if not mandate_by_id:
        return []

    def time_key(value: Any) -> float:
        timestamp = getattr(value, "timestamp", None)
        return float(timestamp()) if callable(timestamp) else 0.0

    mandate_ids = list(mandate_by_id)
    from app.api.consumer_result import DELIVERY_EVENT
    delivered_acquisitions = {
        (event.mandate_id, acquisition_id)
        for event in session.query(UsageEvent).filter(
            UsageEvent.mandate_id.in_(mandate_ids), UsageEvent.event_type == DELIVERY_EVENT
        ).all()
        if event.event_type == DELIVERY_EVENT
        and (event.metadata_ or {}).get("delivery_surface") == "x402-public-result"
        and (event.metadata_ or {}).get("delivery_scope") == "SERVER_DELIVERY_CONFIRMED"
        for acquisition_id in (event.metadata_ or {}).get("acquisition_ids", [])
    }
    tasks = [
        item for item in session.query(AcquisitionTask)
        .filter(AcquisitionTask.mandate_id.in_(mandate_ids)).all()
        if str(getattr(item, "mandate_id", "")) in mandate_by_id
    ]
    if not tasks:
        return []

    task_ids = {str(item.acquisition_id) for item in tasks}
    task_by_id = {str(item.acquisition_id): item for item in tasks}
    calls = [
        item for item in session.query(TelegraphCall)
        .filter(TelegraphCall.mandate_id.in_(mandate_ids)).all()
        if str(getattr(item, "acquisition_id", "")) in task_ids
        and str(getattr(item, "mandate_id", "")) == str(task_by_id[str(item.acquisition_id)].mandate_id)
    ]
    call_by_task = {str(item.acquisition_id): item for item in calls}
    task_by_call_id = {
        str(item.telegraph_call_id): str(item.acquisition_id)
        for item in calls if getattr(item, "telegraph_call_id", None)
    }
    evidences = [
        item for item in session.query(Evidence)
        .filter(Evidence.mandate_id.in_(mandate_ids)).all()
        if str(getattr(item, "mandate_id", "")) in mandate_by_id
    ]
    evidences.sort(key=lambda item: (time_key(getattr(item, "created_at", None)), str(getattr(item, "evidence_id", ""))))
    evidence_by_task: dict[str, Evidence] = {}
    for item in evidences:
        acquisition_id = getattr(item, "acquisition_id", None)
        call_id = getattr(item, "telegraph_call_id", None)
        linked_task = task_by_id.get(str(acquisition_id)) if acquisition_id else None
        if linked_task and str(linked_task.mandate_id) == str(item.mandate_id):
            evidence_by_task[str(acquisition_id)] = item
        elif call_id and str(call_id) in task_by_call_id:
            task_id = task_by_call_id[str(call_id)]
            linked_call = call_by_task[task_id]
            if str(getattr(linked_call, "mandate_id", "")) == str(item.mandate_id):
                evidence_by_task[task_id] = item

    decisions = [
        item for item in session.query(Decision)
        .filter(Decision.mandate_id.in_(mandate_ids)).all()
        if str(getattr(item, "mandate_id", "")) in mandate_by_id
    ]
    decisions.sort(key=lambda item: (time_key(getattr(item, "created_at", None)), str(getattr(item, "decision_id", ""))))
    decision_by_mandate: dict[str, Decision] = {}
    for item in decisions:
        decision_by_mandate[str(item.mandate_id)] = item

    payments = [
        item for item in session.query(InboundX402Payment)
        .filter(InboundX402Payment.mandate_id.in_(mandate_ids)).all()
        if str(getattr(item, "mandate_id", "")) in mandate_by_id
        and getattr(item, "payment_status", None) == "SETTLED"
    ]
    payments.sort(key=lambda item: (time_key(getattr(item, "settled_at", None) or getattr(item, "created_at", None)), str(getattr(item, "payment_id", ""))))
    payment_by_mandate: dict[str, InboundX402Payment] = {}
    for item in payments:
        payment_by_mandate[str(item.mandate_id)] = item

    policy_ids = {str(item.autonomy_policy_id) for item in visible_mandates if getattr(item, "autonomy_policy_id", None)}
    policies = {
        str(item.policy_id): item
        for item in session.query(AutonomyPolicy).all()
        if str(getattr(item, "policy_id", "")) in policy_ids
    }

    rows: list[tuple[float, str, dict[str, Any]]] = []
    for task in tasks:
        mandate_id = str(task.mandate_id)
        mandate = mandate_by_id[mandate_id]
        call = call_by_task.get(str(task.acquisition_id))
        evidence = evidence_by_task.get(str(task.acquisition_id))
        decision = decision_by_mandate.get(mandate_id)
        payment = payment_by_mandate.get(mandate_id)
        origin = str(getattr(mandate, "origin", "") or "")
        if origin == "AUTONOMOUS" and _is_fixture_policy(policies.get(str(getattr(mandate, "autonomy_policy_id", "")))):
            origin = "FIXTURE / CANARY"
        elif origin not in {"M2M", "MANUAL", "AUTONOMOUS"}:
            origin = "LEGACY / UNATTRIBUTED"
        timestamp = (
            getattr(call, "completed_at", None)
            or getattr(task, "completed_at", None)
            or getattr(call, "created_at", None)
            or getattr(task, "started_at", None)
            or getattr(task, "created_at", None)
        )
        query = str(getattr(task, "query", "") or "")
        rows.append((time_key(timestamp), str(task.acquisition_id), {
            "time": _iso(timestamp),
            "origin": origin,
            "client": getattr(mandate, "agent_id", None) or getattr(mandate, "client_id", None),
            "intent": getattr(call, "intent", None) or getattr(task, "requested_intent", None),
            "query": query[:240],
            "payment_amount_usdc": _money(getattr(payment, "amount_usdc", None)) if payment else None,
            "acquisition_status": getattr(task, "status", None),
            "evidence_status": getattr(evidence, "admissibility", None),
            "evidence_sha": getattr(evidence, "content_hash", None),
            "decision": getattr(decision, "state", None),
            "delivery_status": "DELIVERED" if (task.mandate_id, task.acquisition_id) in delivered_acquisitions else "UNKNOWN",
        }))

    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in rows[:max(0, limit)]]


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


def _activity_aggregate(session: Session, mandates: list[Mandate]) -> dict[str, Any]:
    if not mandates:
        return {
            "real_users": 0, "workflows_started": 0, "workflows_completed": 0,
            "telegraph_calls": 0, "telegraph_successful_calls": 0,
            "real_miners_used": [], "intents_used": [], "multi_intent_workflows": 0,
            "evidence_created": 0, "decisions_emitted": 0, "tickets_emitted": 0,
            "requester_principals": [],
            "public_spend_usdc": "0.000000",
            **_activity_read_model(session, mandates, [], []),
        }
    mandate_ids = [item.mandate_id for item in mandates]
    tasks = session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id.in_(mandate_ids)).all()
    calls = session.query(TelegraphCall).filter(TelegraphCall.mandate_id.in_(mandate_ids)).all()
    evidence = session.query(Evidence).filter(Evidence.mandate_id.in_(mandate_ids)).all()
    decisions = session.query(Decision).filter(Decision.mandate_id.in_(mandate_ids)).all()
    tickets = session.query(Ticket).filter(Ticket.mandate_id.in_(mandate_ids)).all()
    actor_counts = Counter(item.actor_id for item in mandates)
    successful_calls = [item for item in calls if item.status == "SUCCEEDED"]
    intents_by_mandate: dict[str, set[str]] = {}
    for item in successful_calls:
        if item.intent:
            intents_by_mandate.setdefault(item.mandate_id, set()).add(item.intent)
    spend = sum((Decimal(item.cost_usd or 0) for item in successful_calls), Decimal("0"))
    requester_principals = sorted({str(getattr(item, "client_id", "")) for item in mandates if item.origin == "M2M" and getattr(item, "client_id", None)})
    read_model = _activity_read_model(session, mandates, calls, evidence)
    return {
        "real_users": len(actor_counts),
        "workflows_started": len(mandates),
        "workflows_completed": sum(item.status == "TICKETED" for item in mandates),
        "telegraph_calls": len(calls),
        "telegraph_successful_calls": len(successful_calls),
        "real_miners_used": sorted({str(item.miner_id) for item in successful_calls if item.miner_id}),
        "intents_used": sorted({str(item.intent) for item in successful_calls if item.intent}),
        "multi_intent_workflows": sum(len(intents) > 1 for intents in intents_by_mandate.values()),
        "evidence_created": len(evidence),
        "decisions_emitted": len(decisions),
        "tickets_emitted": len(tickets),
        # client_id is bound to the authenticated M2M token context at intake;
        # it identifies the declared requester, not a Telegraph payment payer.
        "requester_principals": requester_principals,
        "public_spend_usdc": _money(spend),
        **read_model,
    }


def _is_fixture_policy(policy: AutonomyPolicy | None) -> bool:
    """Classify only the explicitly named fixture/canary policies.

    The policy table has no durable demand-classification column.  Keeping the
    allow-list here makes the public label honest: autonomous records from an
    unknown policy remain unattributed instead of being presented as demand.
    """
    if policy is None:
        return False
    name = str(getattr(policy, "name", ""))
    if name in FIXTURE_POLICY_NAMES:
        return True
    normalized = name.lower()
    return "fixture" in normalized or "canary" in normalized


def _demand_origin_summary(session: Session) -> dict[str, Any]:
    """Count processed Miner responses by their persisted causal origin."""
    mandates = {item.mandate_id: item for item in session.query(Mandate).all()}
    policies = {item.policy_id: item for item in session.query(AutonomyPolicy).all()}
    calls = session.query(TelegraphCall).all()
    processed = [item for item in calls if _processed_call(item)]
    counts = Counter()
    for call in processed:
        mandate = mandates.get(getattr(call, "mandate_id", None))
        origin = getattr(mandate, "origin", None)
        if origin in PUBLIC_ORIGINS:
            counts["external_user_driven"] += 1
            counts[{"MANUAL": "manual", "M2M": "m2m_inbound", "USER": "user"}[origin]] += 1
        elif origin == "AUTONOMOUS" and _is_fixture_policy(policies.get(getattr(mandate, "autonomy_policy_id", None))):
            counts["fixture_canary"] += 1
        else:
            counts["unattributed_legacy"] += 1
    return {
        "total": len(processed),
        "external_user_driven": counts["external_user_driven"],
        "manual": counts["manual"],
        "m2m_inbound": counts["m2m_inbound"],
        "user": counts["user"],
        "fixture_canary": counts["fixture_canary"],
        "unattributed_legacy": counts["unattributed_legacy"],
    }


def public_activity(session: Session) -> dict[str, Any]:
    """Build bounded activity aggregates from public-origin records only.

    The database does not persist an independent TEST/SHADOW/INTERNAL
    environment label for every historical row.  The response therefore
    states the exact origin-based scope instead of guessing those categories.

    Autonomous-origin aggregates are reported separately, so manual and M2M
    counts stay clean while the live agent still becomes visible when it is
    actually executing and settling Telegraph calls.
    """

    mandates = _public_mandates(session)
    manual = [item for item in mandates if item.origin == "MANUAL"]
    m2m = [item for item in mandates if item.origin == "M2M"]
    user = [item for item in mandates if item.origin == "USER"]
    autonomous = [item for item in session.query(Mandate).all() if item.origin == "AUTONOMOUS"]
    autonomous_summary = _activity_aggregate(session, autonomous)
    manual_summary = _activity_aggregate(session, manual)
    m2m_summary = _activity_aggregate(session, m2m)
    user_summary = _activity_aggregate(session, user)
    operational_ledger = _operational_ledger(session, mandates, autonomous)
    all_mandates = [*mandates, *autonomous]
    all_mandate_ids = [item.mandate_id for item in all_mandates]
    all_calls = session.query(TelegraphCall).filter(TelegraphCall.mandate_id.in_(all_mandate_ids)).all() if all_mandate_ids else []
    all_evidence = session.query(Evidence).filter(Evidence.mandate_id.in_(all_mandate_ids)).all() if all_mandate_ids else []
    all_read_model = _activity_read_model(session, all_mandates, all_calls, all_evidence)
    demand_origin = _demand_origin_summary(session)
    execution_history = _execution_history(session, all_mandates)

    mandate_ids = [item.mandate_id for item in mandates]
    if not mandate_ids:
        base = {
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
            "inbound_m2m_requests": 0,
            "inbound_m2m_requester_principals": [],
            **all_read_model,
            "demand_origin": demand_origin,
            "execution_history": execution_history,
        }
        base["autonomous"] = autonomous_summary
        base["manual"] = manual_summary
        base["m2m"] = m2m_summary
        base["user"] = user_summary
        base["operational_ledger"] = operational_ledger
        return base

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
    read_model = all_read_model

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
        **read_model,
        "inbound_m2m_requests": m2m_summary["workflows_started"],
        "inbound_m2m_requester_principals": m2m_summary["requester_principals"],
        "manual": manual_summary,
        "m2m": m2m_summary,
        "user": user_summary,
        "autonomous": autonomous_summary,
        "operational_ledger": operational_ledger,
        "demand_origin": demand_origin,
        "execution_history": execution_history,
    }


def _operational_ledger(session: Session, public_mandates: list[Mandate], autonomous: list[Mandate]) -> dict[str, Any]:
    """Build the read-only ledger from persisted production records."""
    all_mandates = [*public_mandates, *autonomous]
    autonomous_ids = {item.mandate_id for item in autonomous}
    autonomous_tasks = [task for task in session.query(AcquisitionTask).all() if task.mandate_id in autonomous_ids]
    autonomous_calls = [call for call in session.query(TelegraphCall).all() if call.mandate_id in autonomous_ids]
    call_counts = Counter(str(call.status) for call in autonomous_calls)
    authority_codes = {"AUTHORITY_COMPOSITION_RESTRICTED", "G13_REVIEW"}
    task_failures = [task for task in autonomous_tasks if task.failure_code]
    call_acquisition_ids = {call.acquisition_id for call in autonomous_calls}

    authority_reason = func.jsonb_extract_path_text(PolicyEvaluation.result_core, "authority_reason")
    authority_counts = Counter()
    try:
        authority_rows = (
            session.query(authority_reason, func.count(PolicyEvaluation.policy_evaluation_id))
            .filter(PolicyEvaluation.policy_type == "AUTHORITY_COMPOSITION")
            .group_by(authority_reason)
            .all()
        )
    except (AttributeError, TypeError):
        # Lightweight test/read-only Session implementations may only expose
        # model queries; keep the same derived semantics for those callers.
        evaluations = session.query(PolicyEvaluation).all()
        fallback = Counter()
        for evaluation in evaluations:
            if evaluation.policy_type != "AUTHORITY_COMPOSITION":
                continue
            core = evaluation.result_core or {}
            triggered = evaluation.triggered_rule_ids or []
            fallback[str(core.get("authority_reason") or (triggered[0] if triggered else "UNKNOWN"))] += 1
        authority_rows = fallback.items()
    for reason, count in authority_rows:
        authority_counts[str(reason or "UNKNOWN")] += int(count)

    return {
        "mandates": {
            "total": len(all_mandates),
            "ticketed": sum(item.status == "TICKETED" for item in all_mandates),
            "manual": sum(item.origin == "MANUAL" for item in all_mandates),
            "m2m": sum(item.origin == "M2M" for item in all_mandates),
            "user": sum(item.origin == "USER" for item in all_mandates),
            "autonomous": len(autonomous),
        },
        "autonomous_outcomes": {
            "telegraph_succeeded": call_counts.get("SUCCEEDED", 0),
            "authority_restricted": sum(task.failure_code in authority_codes for task in task_failures),
            "composition_restricted": sum(task.failure_code == "AUTHORITY_COMPOSITION_RESTRICTED" for task in task_failures),
            "g13_review": sum(task.failure_code == "G13_REVIEW" for task in task_failures),
            "external_worker_failures": sum(task.failure_code not in authority_codes for task in task_failures),
            "running": sum(task.status == "RUNNING" for task in autonomous_tasks),
        },
        "telegraph_call_state": {
            "succeeded": call_counts.get("SUCCEEDED", 0),
            "reconciled_no_payment": call_counts.get("RECONCILED_NO_PAYMENT", 0),
            "payment_uncertain": call_counts.get("PAYMENT_UNCERTAIN", 0),
            "requested": call_counts.get("REQUESTED", 0),
            "not_executed": call_counts.get("NOT_EXECUTED", 0),
            "no_telegraph_call": sum(task.acquisition_id not in call_acquisition_ids for task in autonomous_tasks),
        },
        "authority": {
            "next_action_authorized": authority_counts.get("NEXT_ACTION_AUTHORIZED", 0),
            "g13_review": authority_counts.get("G13_REVIEW", 0),
            "g13_throttle": authority_counts.get("G13_THROTTLE_CONSTRAINTS_REQUIRED", 0),
        },
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
                "requested_intent": getattr(task, "requested_intent", None),
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
