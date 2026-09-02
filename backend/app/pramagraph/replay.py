from app.domain.mandates import Evidence, StructuralEvaluation, Decision
from app.pramagraph.evaluation import digest, decide
def replay(session, mandate_id):
    es=session.query(Evidence).filter_by(mandate_id=mandate_id).all()
    hashes=[]
    for e in es:
        value=digest(e.normalized_payload)
        if value!=e.content_hash: raise ValueError("CONTENT_HASH_MISMATCH")
        hashes.append((e.evidence_id,value))
    evidence_set_hash=digest([h for _,h in sorted(hashes)])
    ev=session.query(StructuralEvaluation).filter_by(mandate_id=mandate_id).first(); d=session.query(Decision).filter_by(mandate_id=mandate_id).first()
    state="STRUCTURALLY_BLOCKED" if not es or any(e.admissibility=="REJECTED" for e in es) else ("STRUCTURALLY_LIMITED" if any(e.admissibility=="LIMITED" for e in es) else "STRUCTURALLY_ADMISSIBLE")
    decision,reasons=decide(state)
    return {"content_hashes":[h for _,h in hashes],"evidence_set_hash":evidence_set_hash,"structural_state":state,"decision":decision,"reason_codes":reasons,"matches":bool(ev and d and ev.evidence_set_hash==evidence_set_hash and d.state==decision and d.reason_codes==reasons)}
