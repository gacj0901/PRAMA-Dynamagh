"""Sequential explicit fan-out with a durable at-most-once payment claim.

PostgreSQL serializes claims across tasks and deliveries. A network outcome
that cannot be established holds its maximum and is never paid again.
"""
import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import Request, urlopen

from app.domain.mandates import AcquisitionTask, TelegraphCall, Mandate, MandateStatus, PublicManualSpendReservation, UsageEvent
from app.domain.state_machine import transition_mandate
from app.persistence.database import SessionLocal
from app.public_safety import MAX_SINGLE_ACQUISITION_USDC, M2M_MAX_WORKFLOW_USDC, m2m_max_workflow_usdc, public_max_mandate_usdc, verify_spend_reservation, settle_spend, release_spend_reservation

logger = logging.getLogger(__name__)
now = lambda: datetime.now(timezone.utc)


def maximum(mandate):
    if mandate.origin == "M2M": return m2m_max_workflow_usdc()
    if mandate.origin == "AUTONOMOUS": return M2M_MAX_WORKFLOW_USDC
    return public_max_mandate_usdc()


def uncertain_hold(session, mandate_id):
    events = session.query(UsageEvent).filter_by(mandate_id=mandate_id, event_type="ACQUISITION_PAYMENT_UNCERTAIN").all()
    return sum((Decimal(e.metadata_["held_budget_usdc"]) for e in events), Decimal("0"))


def execute_one(mandate_id, acquisition_id):
    session = SessionLocal()
    network_attempted = False
    budget = Decimal("0")
    claimed = False
    try:
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one_or_none()
        task = session.get(AcquisitionTask, acquisition_id)
        if mandate is None or task is None or task.mandate_id != mandate_id:
            return "INVALID_MANDATE"
        if task.status in {"SUCCEEDED", "FAILED", "RUNNING"}:
            return "ALREADY_" + task.status
        if mandate.status in {"TICKETED", "DECIDED", "FAILED"}:
            return "MANDATE_TERMINAL"
        tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).order_by(AcquisitionTask.ordinal, AcquisitionTask.acquisition_id).all()
        pending = [t for t in tasks if t.status in {"QUEUED", "PENDING"}]
        if any(t.status == "RUNNING" for t in tasks) or not pending or pending[0].acquisition_id != acquisition_id:
            return "WAITING_FOR_PREVIOUS_ACQUISITION"
        if mandate.status == "RECEIVED": transition_mandate(session, mandate, MandateStatus.PLANNED)
        if mandate.status == "PLANNED": transition_mandate(session, mandate, MandateStatus.ACQUIRING)
        task.status = "RUNNING"
        task.attempt_count += 1
        task.started_at = now()
        claimed = True
        session.commit()
        cap = maximum(mandate)
        if Decimal(mandate.max_budget_usdc) > cap: raise RuntimeError("WORKFLOW_BUDGET_EXCEEDED")
        reservation = verify_spend_reservation(session, mandate_id, cap, mandate.origin)
        available = reservation.reserved_usdc - uncertain_hold(session, mandate_id)
        budget = min(available, MAX_SINGLE_ACQUISITION_USDC)
        if budget <= 0: raise RuntimeError("BUDGET_EXHAUSTED")
        if not task.query.strip(): raise RuntimeError("ACQUISITION_QUERY_INVALID")
        call = TelegraphCall(mandate_id=mandate_id, acquisition_id=acquisition_id, causal_request_id=mandate_id, raw_response={}, status="REQUESTED", cost_usd=None)
        session.add(call)
        session.add(UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id, event_type="TELEGRAPH_REQUEST", metadata_={"budget_usdc":str(budget),"origin":mandate.origin}))
        session.commit()  # Durable RUNNING claim before any outbound request.
        from app.authority.runtime import observe_authority_shadow
        observe_authority_shadow(mandate_id, phase="PRE_ACQUISITION", acquisition_id=acquisition_id)
        payload = {"query":task.query,"context":({"requested_intent":task.requested_intent} if task.requested_intent else {}),"causal_request_id":mandate_id,"budget_usdc":str(budget)}
        request = Request(os.environ["GATEWAY_URL"] + "/ask",data=json.dumps(payload).encode(),headers={"content-type":"application/json"},method="POST")
        network_attempted = True
        with urlopen(request,timeout=45) as response: raw = json.loads(response.read())
        call.raw_response = raw if isinstance(raw,dict) else {"gateway_response":raw}
        call.status = "RECEIVED"
        session.commit()  # Preserve Gateway response before Evidence normalization.
        if not isinstance(raw,dict) or not all(raw.get(k) for k in ("miner_id","intent","signal_hash")):
            raise RuntimeError("TELEGRAPH_INVALID_RESPONSE")
        cost_value = (raw.get("payment") or {}).get("amount_usdc",raw.get("cost_usd"))
        if cost_value is None: raise RuntimeError("PAYMENT_COST_UNAVAILABLE")
        actual = Decimal(str(cost_value))
        if not actual.is_finite() or actual < 0 or actual > budget or actual.as_tuple().exponent < -6:
            raise RuntimeError("SINGLE_ACQUISITION_BUDGET_EXCEEDED")
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one()
        queued = session.query(AcquisitionTask).filter(AcquisitionTask.mandate_id==mandate_id,AcquisitionTask.status.in_(["QUEUED","PENDING"])).count()
        settle_spend(session,mandate_id,actual,cap,mandate.origin,finalize=not queued and uncertain_hold(session,mandate_id)==0)
        for name in ["miner_id","miner_name","intent","signal_hash","duration_ms","reasoning"]:
            setattr(call,name,raw.get(name))
        call.miner_id = str(raw["miner_id"])
        call.warnings = raw.get("warnings") or []
        call.cost_usd = actual
        call.status = "SUCCEEDED"
        call.completed_at = task.completed_at = now()
        task.status = "SUCCEEDED"
        for kind in ["TELEGRAPH_RESPONSE","ACQUISITION_COMPLETED"]:
            session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type=kind,metadata_={"origin":mandate.origin}))
        session.commit()
        return "ACQUISITION_COMPLETED"
    except Exception as error:
        session.rollback()
        if not claimed: raise
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one()
        task = session.get(AcquisitionTask,acquisition_id)
        known = {"WORKFLOW_BUDGET_EXCEEDED","BUDGET_EXHAUSTED","ACQUISITION_QUERY_INVALID","TELEGRAPH_INVALID_RESPONSE","PAYMENT_COST_UNAVAILABLE","SINGLE_ACQUISITION_BUDGET_EXCEEDED","PUBLIC_SPEND_AUTHORIZATION_INVALID","PUBLIC_SPEND_AUTHORIZATION_UNAVAILABLE","PUBLIC_SPEND_SETTLEMENT_INVALID"}
        message = getattr(error,"detail",str(error))
        code = message if message in known else "GATEWAY_UNAVAILABLE"
        task.status = "FAILED"
        task.failure_code = code
        task.started_at = task.started_at or now()
        task.completed_at = now()
        task.attempt_count = max(task.attempt_count,1)
        # A claim failing before its first commit also needs explicit transitions.
        if mandate.status == "RECEIVED": transition_mandate(session,mandate,MandateStatus.PLANNED)
        if mandate.status == "PLANNED": transition_mandate(session,mandate,MandateStatus.ACQUIRING)
        call = session.query(TelegraphCall).filter_by(acquisition_id=acquisition_id).one_or_none()
        if call:
            call.status = "PAYMENT_UNCERTAIN" if network_attempted else "NOT_EXECUTED"
            call.completed_at = now()
        session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_FAILED",metadata_={"failure_code":code,"network_attempted":network_attempted}))
        if network_attempted:
            session.add(UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_PAYMENT_UNCERTAIN",metadata_={"held_budget_usdc":str(budget),"failure_code":code}))
        session.commit()
        return code
    finally:
        session.close()


def advance(mandate_id):
    """Resume dispatch on redelivery without repeating completed payment."""
    session = SessionLocal()
    try:
        mandate = session.query(Mandate).filter_by(mandate_id=mandate_id).with_for_update().one_or_none()
        if mandate is None: return "INVALID_MANDATE"
        if mandate.status in {"TICKETED","FAILED"}: return mandate.status
        tasks = session.query(AcquisitionTask).filter_by(mandate_id=mandate_id).order_by(AcquisitionTask.ordinal).all()
        if any(t.status=="RUNNING" for t in tasks): return "WAITING_FOR_ACQUISITIONS"
        queued = next((t for t in tasks if t.status in {"QUEUED","PENDING"}),None)
        if queued:
            next_id = queued.acquisition_id
            session.commit()
            from app.workers.tasks import execute_acquisition
            execute_acquisition.delay(mandate_id,next_id)
            return "ACQUISITION_CONTINUED"
        if mandate.status == "ACQUIRING":
            reservation = session.get(PublicManualSpendReservation,mandate_id)
            if reservation and reservation.status=="RESERVED" and uncertain_hold(session,mandate_id)==0:
                if reservation.reserved_usdc>0:
                    settle_spend(session,mandate_id,Decimal("0"),maximum(mandate),mandate.origin,finalize=True)
                else:
                    release_spend_reservation(session,mandate_id,mandate.origin)
            transition_mandate(session,mandate,MandateStatus.EVALUATING)
        session.commit()
    finally: session.close()
    from app.workers.tasks import evaluate_mandate
    return evaluate_mandate(mandate_id)
