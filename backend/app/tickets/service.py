from app.domain.mandates import *
from app.domain.state_machine import transition_mandate
from app.tickets.core import build,hash_core
def issue(s,mid):
  m=s.get(Mandate,mid); old=s.query(Ticket).filter_by(mandate_id=mid).first()
  if old:return old,'ALREADY_TICKETED'
  if m.status!='DECIDED':raise ValueError('MANDATE_NOT_DECIDED')
  d=s.query(Decision).filter_by(mandate_id=mid).one(); e=s.query(StructuralEvaluation).filter_by(mandate_id=mid).one(); es=s.query(Evidence).filter_by(mandate_id=mid).all(); ts=s.query(AcquisitionTask).filter_by(mandate_id=mid).all(); cs=s.query(TelegraphCall).filter_by(mandate_id=mid).all(); core=build(m,d,e,es,cs,ts); t=Ticket(mandate_id=mid,decision_id=d.decision_id,schema_version='prama.ticket.v0',canonical_payload=core,ticket_hash=hash_core(core),hash_algorithm='keccak256',anchor_status='LOCAL_ONLY');s.add(t);s.flush();transition_mandate(s,m,MandateStatus.TICKETED);s.add(UsageEvent(mandate_id=mid,event_type='TICKET_CREATED',metadata_={'origin':m.origin,'agent_id':m.agent_id or '','client_id':m.client_id or ''}));s.commit();return t,'TICKETED'
def verify(s,t):
 m=s.get(Mandate,t.mandate_id);d=s.get(Decision,t.decision_id);e=s.query(StructuralEvaluation).filter_by(mandate_id=m.mandate_id).one();es=s.query(Evidence).filter_by(mandate_id=m.mandate_id).all();ts=s.query(AcquisitionTask).filter_by(mandate_id=m.mandate_id).all();cs=s.query(TelegraphCall).filter_by(mandate_id=m.mandate_id).all(); core=build(m,d,e,es,cs,ts); return {'status':'VALID' if hash_core(t.canonical_payload)==t.ticket_hash and core==t.canonical_payload else 'INVALID','ticket_hash':t.ticket_hash,'payload_hash_match':hash_core(t.canonical_payload)==t.ticket_hash,'source_artifacts_match':core==t.canonical_payload,'failure_codes':[]}
