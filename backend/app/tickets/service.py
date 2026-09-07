from app.domain.mandates import *
from app.agents.identity import mandate_attribution
from app.domain.state_machine import transition_mandate
from app.tickets.core import build,hash_core
from app.tickets.disclosure import ensure_issued
def issue(s,mid):
  m=s.query(Mandate).filter_by(mandate_id=mid).with_for_update().one(); old=s.query(Ticket).filter_by(mandate_id=mid).first()
  if old:return old,'ALREADY_TICKETED'
  if m.status!='DECIDED':raise ValueError('MANDATE_NOT_DECIDED')
  d=s.query(Decision).filter_by(mandate_id=mid).one(); e=s.query(StructuralEvaluation).filter_by(mandate_id=mid).one(); es=s.query(Evidence).filter_by(mandate_id=mid).all(); ts=s.query(AcquisitionTask).filter_by(mandate_id=mid).all(); cs=s.query(TelegraphCall).filter_by(mandate_id=mid).all(); core=build(m,d,e,es,cs,ts); t=Ticket(mandate_id=mid,decision_id=d.decision_id,schema_version=core['schema_version'],canonical_payload=core,ticket_hash=hash_core(core),hash_algorithm='keccak256',anchor_status='LOCAL_ONLY');s.add(t);s.flush();transition_mandate(s,m,MandateStatus.TICKETED);s.add(UsageEvent(mandate_id=mid,event_type='TICKET_CREATED',metadata_=mandate_attribution(m)));ensure_issued(s,t);s.commit();return t,'TICKETED'
def verify(s,t):
 from app.tickets.public_identity import normalized_hash
 m=s.get(Mandate,t.mandate_id);d=s.get(Decision,t.decision_id);e=s.query(StructuralEvaluation).filter_by(mandate_id=m.mandate_id).one();es=s.query(Evidence).filter_by(mandate_id=m.mandate_id).all();ts=s.query(AcquisitionTask).filter_by(mandate_id=m.mandate_id).all();cs=s.query(TelegraphCall).filter_by(mandate_id=m.mandate_id).all(); core=build(m,d,e,es,cs,ts)
 payload_match = normalized_hash(hash_core(t.canonical_payload)) == normalized_hash(t.ticket_hash)
 return {'status':'VALID' if payload_match and core==t.canonical_payload else 'INVALID','ticket_hash':t.ticket_hash,'reconstructed_hash':hash_core(core),'payload_hash_match':payload_match,'source_artifacts_match':core==t.canonical_payload,'failure_codes':[]}
