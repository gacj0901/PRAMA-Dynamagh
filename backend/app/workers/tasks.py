import json, os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
import redis
from app.workers.celery_app import celery_app
from app.persistence.database import SessionLocal
from app.domain.mandates import AcquisitionTask, AcquisitionStatus, Mandate, MandateStatus, TelegraphCall, UsageEvent
from app.domain.state_machine import transition_mandate

def now(): return datetime.now(timezone.utc)
@celery_app.task(name="prama.execute_acquisition", bind=True)
def execute_acquisition(self, mandate_id: str, acquisition_id: str):
    lock=redis.from_url(os.environ["REDIS_URL"]); key=f"prama:acquisition:{acquisition_id}"
    if not lock.set(key, "1", nx=True, ex=300): return "LOCKED"
    s=SessionLocal()
    try:
        task=s.get(AcquisitionTask, acquisition_id); mandate=s.get(Mandate, mandate_id)
        if not task or not mandate: return "INVALID_MANDATE"
        if task.status == AcquisitionStatus.SUCCEEDED.value: return "ALREADY_COMPLETED"
        if mandate.status == MandateStatus.RECEIVED.value: transition_mandate(s, mandate, MandateStatus.PLANNED)
        task.status=AcquisitionStatus.RUNNING.value; task.attempt_count += 1; task.started_at=now()
        if mandate.status == MandateStatus.PLANNED.value: transition_mandate(s, mandate, MandateStatus.ACQUIRING)
        spent=sum((c.cost_usd or 0 for c in s.query(TelegraphCall).filter_by(mandate_id=mandate_id,status="SUCCEEDED")), Decimal("0")); remaining=Decimal(mandate.max_budget_usdc)-spent
        if remaining <= 0: raise RuntimeError("BUDGET_EXHAUSTED")
        s.add(UsageEvent(mandate_id=mandate_id, acquisition_id=acquisition_id,event_type="TELEGRAPH_REQUEST",metadata_={})); s.commit()
        data=json.dumps({"query":task.query,"context":{},"causal_request_id":mandate_id,"budget_usdc":str(remaining)}).encode()
        req=Request(os.environ["GATEWAY_URL"]+"/ask",data=data,headers={"content-type":"application/json"},method="POST")
        with urlopen(req, timeout=45) as r: raw=json.loads(r.read())
        if not raw.get("miner_id") or not raw.get("intent") or not raw.get("signal_hash"): raise RuntimeError("TELEGRAPH_INVALID_RESPONSE")
        call=TelegraphCall(mandate_id=mandate_id,acquisition_id=acquisition_id,causal_request_id=mandate_id,miner_id=str(raw.get("miner_id")),miner_name=raw.get("miner_name"),intent=raw.get("intent"),signal_hash=raw.get("signal_hash"),cost_usd=raw.get("cost_usd"),duration_ms=raw.get("duration_ms"),reasoning=raw.get("reasoning"),warnings=raw.get("warnings",[]),raw_response=raw,status="SUCCEEDED",completed_at=now())
        s.add(call); task.status=AcquisitionStatus.SUCCEEDED.value; task.completed_at=now(); transition_mandate(s,mandate,MandateStatus.EVALUATING); s.add_all([UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="TELEGRAPH_RESPONSE",metadata_={}),UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_COMPLETED",metadata_={})]); s.commit(); return "SUCCEEDED"
    except Exception as e:
        code=str(e) if str(e) in {"BUDGET_EXHAUSTED","TELEGRAPH_INVALID_RESPONSE"} else "GATEWAY_UNAVAILABLE"; task=s.get(AcquisitionTask,acquisition_id); mandate=s.get(Mandate,mandate_id)
        if task: task.status=AcquisitionStatus.FAILED.value; task.failure_code=code
        if mandate and mandate.status not in {"FAILED","TICKETED"}: transition_mandate(s,mandate,MandateStatus.FAILED,code)
        s.commit(); return code
    finally: lock.delete(key); s.close()
