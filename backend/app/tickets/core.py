from decimal import Decimal
from app.pramagraph.evaluation import canonical,digest
def money(v): return f"{Decimal(v):.6f}"
def build(mandate,decision,evaluation,evidence,calls,tasks):
    by={t.acquisition_id:t for t in tasks}
    subject=(getattr(mandate,"constraints",{}) or {}).get("ticket_subject_id",mandate.mandate_id)
    return {"schema_version":"prama.ticket.v0","mandate":{"mandate_id":subject,"mandate_type":mandate.mandate_type},"decision":{"state":decision.state,"policy_version":decision.policy_version,"reason_codes":sorted(decision.reason_codes)},"evaluation":{"evaluator":evaluation.evaluator,"evaluator_version":evaluation.evaluator_version,"structural_state":evaluation.structural_state,"evidence_set_hash":evaluation.evidence_set_hash},"evidence":[{"content_hash":e.content_hash,"normalizer_version":e.normalizer_version,"admissibility":e.admissibility,"provenance_status":e.provenance_status,"source_intent":e.source_intent,"source_miner_id":e.source_miner_id,"source_signal_hash":e.source_signal_hash} for e in sorted(evidence,key=lambda x:x.evidence_id)],"telegraph":[{"acquisition_id":c.acquisition_id,"intent":c.intent,"miner_id":c.miner_id,"signal_hash":c.signal_hash,"cost_usd":money(c.cost_usd)} for c in sorted(calls,key=lambda x:(by[x.acquisition_id].ordinal,x.acquisition_id))],"cost_usd_total":money(sum((c.cost_usd or 0 for c in calls),Decimal(0)))}
def hash_core(core): return digest(core)
