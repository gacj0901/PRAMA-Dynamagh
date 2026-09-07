from decimal import Decimal
from app.pramagraph.evaluation import canonical,digest
def money(v): return f"{Decimal(v):.6f}"
def _legacy_build(mandate,decision,evaluation,evidence,calls,tasks):
    by={t.acquisition_id:t for t in tasks}
    subject=(getattr(mandate,"constraints",{}) or {}).get("ticket_subject_id",mandate.mandate_id)
    return {"schema_version":"prama.ticket.v0","mandate":{"mandate_id":subject,"mandate_type":mandate.mandate_type},"decision":{"state":decision.state,"policy_version":decision.policy_version,"reason_codes":sorted(decision.reason_codes)},"evaluation":{"evaluator":evaluation.evaluator,"evaluator_version":evaluation.evaluator_version,"structural_state":evaluation.structural_state,"evidence_set_hash":evaluation.evidence_set_hash},"evidence":[{"content_hash":e.content_hash,"normalizer_version":e.normalizer_version,"admissibility":e.admissibility,"provenance_status":e.provenance_status,"source_intent":e.source_intent,"source_miner_id":e.source_miner_id,"source_signal_hash":e.source_signal_hash} for e in sorted(evidence,key=lambda x:x.evidence_id)],"telegraph":[{"acquisition_id":c.acquisition_id,"intent":c.intent,"miner_id":c.miner_id,"signal_hash":c.signal_hash,"cost_usd":money(c.cost_usd)} for c in sorted(calls,key=lambda x:(by[x.acquisition_id].ordinal,x.acquisition_id))],"cost_usd_total":money(sum((c.cost_usd or 0 for c in calls),Decimal(0)))}
def build(mandate,decision,evaluation,evidence,calls,tasks):
    from app.pramagraph.fanout import VERSION
    if evaluation.evaluator_version != VERSION:
        return _legacy_build(mandate,decision,evaluation,evidence,calls,tasks)
    core=_legacy_build(mandate,decision,evaluation,evidence,[c for c in calls if c.status=='SUCCEEDED'],tasks)
    core['schema_version']='prama.ticket.fanout.v0.1'
    core['acquisitions']=[{'acquisition_id':t.acquisition_id,'ordinal':t.ordinal,'query_hash':digest(t.query),'requested_intent':t.requested_intent,'required':t.required,'status':t.status,'failure_code':t.failure_code} for t in sorted(tasks,key=lambda t:(t.ordinal,t.acquisition_id))]
    core['evaluation']['limitation_codes']=sorted(evaluation.limitation_codes)
    core['evaluation']['contradiction_codes']=sorted(evaluation.contradiction_codes)
    core['unsuccessful_calls']=[{'acquisition_id':c.acquisition_id,'status':c.status,'cost_usd':money(c.cost_usd) if c.cost_usd is not None else None} for c in sorted(calls,key=lambda c:c.acquisition_id) if c.status!='SUCCEEDED']
    core['cost_is_complete']=all(c.cost_usd is not None for c in calls)
    return core

def hash_core(core): return digest(core)
