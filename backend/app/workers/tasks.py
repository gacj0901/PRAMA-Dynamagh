import json, os
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
import redis
from app.workers.celery_app import celery_app
from app.persistence.database import SessionLocal
from app.domain.mandates import AcquisitionTask, AcquisitionStatus, Mandate, MandateStatus, TelegraphCall, UsageEvent, Evidence, StructuralEvaluation, Decision
from app.domain.state_machine import transition_mandate
from app.pramagraph.evaluation import classify, decide, digest
from app.tickets.service import issue as issue_ticket

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
        s.add(call); task.status=AcquisitionStatus.SUCCEEDED.value; task.completed_at=now(); transition_mandate(s,mandate,MandateStatus.EVALUATING); s.add_all([UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="TELEGRAPH_RESPONSE",metadata_={}),UsageEvent(mandate_id=mandate_id,acquisition_id=acquisition_id,event_type="ACQUISITION_COMPLETED",metadata_={})]); s.commit(); return evaluate_mandate(mandate_id)
    except Exception as e:
        code=str(e) if str(e) in {"BUDGET_EXHAUSTED","TELEGRAPH_INVALID_RESPONSE"} else "GATEWAY_UNAVAILABLE"; task=s.get(AcquisitionTask,acquisition_id); mandate=s.get(Mandate,mandate_id)
        if task: task.status=AcquisitionStatus.FAILED.value; task.failure_code=code
        if mandate and mandate.status not in {"FAILED","TICKETED"}: transition_mandate(s,mandate,MandateStatus.FAILED,code)
        s.commit(); return code
    finally: lock.delete(key); s.close()

@celery_app.task(name="prama.evaluate_mandate")
def evaluate_mandate(mandate_id):
    s=SessionLocal()
    try:
        mandate=s.get(Mandate,mandate_id)
        if mandate.status=="DECIDED": return "ALREADY_DECIDED"
        calls=s.query(TelegraphCall).filter_by(mandate_id=mandate_id,status="SUCCEEDED").all()
        if mandate.status=="EVALUATING": transition_mandate(s,mandate,MandateStatus.DECIDING)
        evidence=[]
        for c in calls:
            existing=s.query(Evidence).filter_by(telegraph_call_id=c.telegraph_call_id).one_or_none()
            if existing: evidence.append(existing); continue
            try:
                with urlopen(os.environ["GATEWAY_URL"]+"/signals/"+c.signal_hash,timeout=20) as x: verified=x.status==200
            except: verified=False
            normalized={"intent":c.intent,"result":c.raw_response.get("result"),"miner_id":c.miner_id,"signal_hash":c.signal_hash,"warnings":c.warnings}; adm,codes=classify(c,verified)
            e=Evidence(mandate_id=mandate_id,acquisition_id=c.acquisition_id,telegraph_call_id=c.telegraph_call_id,evidence_type="TELEGRAPH_RESULT",source_kind="TELEGRAPH",source_intent=c.intent,source_miner_id=c.miner_id,source_signal_hash=c.signal_hash,normalized_payload=normalized,content_hash=digest(normalized),normalizer_version="telegraph-evidence-v0",provenance_status="VERIFIED" if verified else "FAILED",admissibility=adm,limitation_codes=codes); s.add(e); evidence.append(e)
        s.flush(); esh=digest([e.content_hash for e in sorted(evidence,key=lambda x:x.evidence_id)])
        rejected=[e.evidence_id for e in evidence if e.admissibility=="REJECTED"]; limited=[e.evidence_id for e in evidence if e.admissibility=="LIMITED"]; admitted=[e.evidence_id for e in evidence if e.admissibility=="ADMITTED"]; structural="STRUCTURALLY_BLOCKED" if not evidence or rejected else ("STRUCTURALLY_LIMITED" if limited else "STRUCTURALLY_ADMISSIBLE")
        ev=StructuralEvaluation(mandate_id=mandate_id,evaluator="PRAMAGRAPH",evaluator_version="pramagraph-structural-v0",evidence_set_hash=esh,admitted_evidence_ids=admitted,limited_evidence_ids=limited,rejected_evidence_ids=rejected,limitation_codes=sum((e.limitation_codes for e in evidence),[]),contradiction_codes=[],structural_state=structural,evaluation_payload={}); s.add(ev); s.flush(); state,reasons=decide(structural); s.add(Decision(mandate_id=mandate_id,evaluation_id=ev.evaluation_id,state=state,policy_version="prama-gate-v0",evidence_set_hash=esh,reason_codes=reasons,decision_payload={})); transition_mandate(s,mandate,MandateStatus.DECIDED); s.add_all([UsageEvent(mandate_id=mandate_id,event_type="EVIDENCE_CREATED",metadata_={}),UsageEvent(mandate_id=mandate_id,event_type="EVALUATION_COMPLETED",metadata_={}),UsageEvent(mandate_id=mandate_id,event_type="DECISION_CREATED",metadata_={})]); s.commit(); return issue_ticket(s,mandate_id)[1]
    finally: s.close()
