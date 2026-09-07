"""Real PostgreSQL pipeline; synthetic Gateway and Redis, never paid traffic."""
import json
import threading
import uuid
import os
import sys
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import mandates as api
from app.domain.mandates import AcquisitionTask, TelegraphCall, Evidence, Decision, Ticket, PolicyEvaluation, PublicManualSpendReservation, PublicManualSpendLedger
from app.persistence.database import SessionLocal
from app.workers import tasks, acquisition
from app.authority import runtime
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope='module')
def track3_database():
    """A migrated disposable schema: append-only rows never pollute other suites."""
    url=make_url(os.environ['DATABASE_URL'])
    assert url.host in {'127.0.0.1','localhost'}, 'Track 3 tests require isolated local PostgreSQL'
    schema='track3_'+uuid.uuid4().hex
    owner=create_engine(url)
    with owner.begin() as c:c.execute(text('CREATE SCHEMA '+schema))
    scoped=url.update_query_dict({'options':'-csearch_path='+schema})
    engine=create_engine(scoped,pool_pre_ping=True)
    env=dict(os.environ,DATABASE_URL=url.render_as_string(hide_password=False),PGOPTIONS='-csearch_path='+schema)
    result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    try:yield sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    finally:
        engine.dispose()
        with owner.begin() as c:c.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        owner.dispose()


class Response:
    status=200
    def __init__(self,body=None): self.body=body
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.body).encode()


class Locks:
    def __init__(self): self.data={};self.mutex=threading.Lock()
    def set(self,key,value,**kwargs):
        with self.mutex:
            if key in self.data:return False
            self.data[key]=value;return True
    def eval(self,script,n,key,token):
        with self.mutex:
            if self.data.get(key)==token:self.data.pop(key);return 1
            return 0


@pytest.fixture
def pipeline(monkeypatch,track3_database):
    from app.persistence import database
    for module in (sys.modules[__name__],tasks,acquisition,runtime,database):
        monkeypatch.setattr(module,'SessionLocal',track3_database)
    monkeypatch.setenv('PUBLIC_MAX_MANDATE_USDC','0.05')
    monkeypatch.setenv('GLOBAL_DAILY_SPEND_CAP_USDC','1.00')
    monkeypatch.setenv('GATEWAY_URL','http://gateway.test')
    monkeypatch.setenv('FANOUT_MAX_TASKS_PER_MANDATE','5')
    monkeypatch.setattr(api,'enforce_public_rate_limit',lambda request:None)
    locks=Locks();monkeypatch.setattr(tasks.redis,'from_url',lambda *a,**k:locks)
    queue=[];payments=[]
    monkeypatch.setattr(tasks.execute_acquisition,'delay',lambda mid,aid:queue.append((mid,aid)))
    def gateway(request,**kwargs):
        body=json.loads(request.data);payments.append(body)
        assert Decimal(body['budget_usdc'])<=Decimal('0.01')
        if body['query']=='timeout':raise TimeoutError('synthetic uncertain outcome')
        return Response({'miner_id':'synthetic-'+body['query'],'intent':'CRYPTO_PRICE' if 'price' in body['query'] else 'GAS_PRICE','signal_hash':'0x'+uuid.uuid4().hex,'cost_usd':'0.006000','result':{'synthetic':True},'warnings':[]})
    monkeypatch.setattr(acquisition,'urlopen',gateway)
    monkeypatch.setattr(tasks,'urlopen',lambda *a,**k:Response())
    def create(queries,budget=None):
        s=SessionLocal()
        try:
            payload=api.MandateCreate(actor_id='track3-test',text='explicit synthetic fanout',acquisitions=[{'query':q} for q in queries],max_budget_usdc=budget or str(Decimal('0.01')*len(queries)))
            m=api.create_mandate(payload,Request({'type':'http','headers':[],'client':('test',1)}),s)
            assert len(m.acquisitions)==len(queries)
            return m.mandate_id
        finally:s.close()
    def drain():
        count=0
        while queue:
            count+=1;assert count<20
            tasks.execute_acquisition(*queue.pop(0))
    return SimpleNamespace(create=create,drain=drain,queue=queue,payments=payments,gateway=gateway)


@pytest.mark.parametrize('n',[2,3])
def test_fanout_lineage_incremental_budget_replay_and_retry(pipeline,n):
    mid=pipeline.create(['price-'+str(i) for i in range(n)])
    first=pipeline.queue.pop(0)
    tasks.execute_acquisition(*first)
    with SessionLocal() as s:
        r=s.get(PublicManualSpendReservation,mid)
        assert r.status=='RESERVED'
        assert r.actual_spend_usdc==Decimal('0.006')
        assert r.reserved_usdc==Decimal('0.01')*n-Decimal('0.006')
    pipeline.drain()
    with SessionLocal() as s:
        acquired=s.query(AcquisitionTask).filter_by(mandate_id=mid).all()
        calls=s.query(TelegraphCall).filter_by(mandate_id=mid).all()
        evidence=s.query(Evidence).filter_by(mandate_id=mid).all()
        assert len(acquired)==len(calls)==len(evidence)==n
        assert {e.acquisition_id for e in evidence}=={a.acquisition_id for a in acquired}
        assert len({e.telegraph_call_id for e in evidence})==n
        assert s.query(Decision).filter_by(mandate_id=mid).count()==1
        ticket=s.query(Ticket).filter_by(mandate_id=mid).one()
        assert ticket.schema_version=='prama.ticket.fanout.v0.1'
        assert len(ticket.canonical_payload['acquisitions'])==n
        from app.tickets.service import verify
        from app.pramagraph.replay import replay
        assert verify(s,ticket)['status']=='VALID'
        assert replay(s,mid)['matches'] is True
        r=s.get(PublicManualSpendReservation,mid)
        assert r.status=='SETTLED' and r.reserved_usdc==0 and r.actual_spend_usdc==Decimal('0.006')*n
        ledger=s.get(PublicManualSpendLedger,r.spend_date)
        ledger_before=(ledger.spent_usdc,ledger.reserved_usdc)
        shadow=s.query(PolicyEvaluation).filter_by(policy_subject_id=mid,policy_id='AUTHORITY_SHADOW_CD').all()
        assert any(row.result=='PERMIT' for row in shadow)
        assert all(row.result_core['details']['typed_e1_available'] is False for row in shadow)
    before=len(pipeline.payments)
    with ThreadPoolExecutor(max_workers=3) as workers:
        list(workers.map(lambda _:tasks.execute_acquisition(*first),range(3)))
    assert len(pipeline.payments)==before
    with SessionLocal() as s:
        r=s.get(PublicManualSpendReservation,mid);ledger=s.get(PublicManualSpendLedger,r.spend_date)
        assert (ledger.spent_usdc,ledger.reserved_usdc)==ledger_before
        assert s.query(Evidence).filter_by(mandate_id=mid).count()==n


def test_invalid_acquisition_does_not_collapse_siblings(pipeline):
    mid=pipeline.create(['price-one','   ','price-three'])
    pipeline.drain()
    assert len(pipeline.payments)==2
    with SessionLocal() as s:
        acquired=s.query(AcquisitionTask).filter_by(mandate_id=mid).order_by(AcquisitionTask.ordinal).all()
        assert [a.status for a in acquired]==['SUCCEEDED','FAILED','SUCCEEDED']
        assert acquired[1].failure_code=='ACQUISITION_QUERY_INVALID'
        assert s.query(Decision).filter_by(mandate_id=mid).one().state=='REVIEW'
        ticket=s.query(Ticket).filter_by(mandate_id=mid).one()
        assert ticket.canonical_payload['acquisitions'][1]['failure_code']=='ACQUISITION_QUERY_INVALID'
        from app.pramagraph.replay import replay
        from app.tickets.service import verify
        assert replay(s,mid)['matches'] and verify(s,ticket)['status']=='VALID'
        reservation=s.get(PublicManualSpendReservation,mid)
        assert reservation.reserved_usdc==0 and reservation.actual_spend_usdc==Decimal('0.012')


def test_uncertain_payment_is_never_retried_or_imputed_zero(pipeline):
    mid=pipeline.create(['price-one','timeout','price-three'])
    pipeline.drain()
    with SessionLocal() as s:
        bad=s.query(AcquisitionTask).filter_by(mandate_id=mid,query='timeout').one()
        bad_id=bad.acquisition_id
        call=s.query(TelegraphCall).filter_by(acquisition_id=bad_id).one()
        assert call.status=='PAYMENT_UNCERTAIN' and call.cost_usd is None
        assert s.get(PublicManualSpendReservation,mid).status=='RESERVED'
        ticket=s.query(Ticket).filter_by(mandate_id=mid).one()
        assert ticket.canonical_payload['cost_is_complete'] is False
        assert s.query(AcquisitionTask).filter_by(mandate_id=mid,status='SUCCEEDED').count()==2
    before=len(pipeline.payments)
    tasks.execute_acquisition(mid,bad_id)
    assert len(pipeline.payments)==before


def test_durable_claim_blocks_concurrent_payment_without_redis(pipeline,monkeypatch):
    mid=pipeline.create(['price-one','price-two'])
    args=pipeline.queue.pop(0)
    entered=threading.Event();release=threading.Event()
    def blocked_gateway(*a,**kw):
        entered.set();assert release.wait(8)
        return pipeline.gateway(*a,**kw)
    monkeypatch.setattr(acquisition,'urlopen',blocked_gateway)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(acquisition.execute_one,*args)
        assert entered.wait(8)
        two=pool.submit(acquisition.execute_one,*args)
        assert two.result(timeout=5)=='ALREADY_RUNNING'
        release.set();assert one.result(timeout=5)=='ACQUISITION_COMPLETED'
    assert len(pipeline.payments)==1
    acquisition.advance(mid);pipeline.drain()


def test_shadow_failure_persists_unavailability_and_does_not_block(pipeline,monkeypatch):
    monkeypatch.setattr(runtime,'_observe',lambda *a,**kw:(_ for _ in ()).throw(ValueError('synthetic shadow failure')))
    mid=pipeline.create(['price-one','price-two']);pipeline.drain()
    with SessionLocal() as s:
        assert s.query(Ticket).filter_by(mandate_id=mid).count()==1
        rows=s.query(PolicyEvaluation).filter_by(policy_subject_id=mid).all()
        assert rows and all(row.result=='UNAVAILABLE' for row in rows)
        assert len(pipeline.payments)==2


def test_count_limit_is_422_before_persistence(pipeline,monkeypatch):
    monkeypatch.setenv('FANOUT_MAX_TASKS_PER_MANDATE','2')
    with pytest.raises(HTTPException) as error:
        pipeline.create(['a','b','c'])
    assert error.value.status_code==422
    assert pipeline.queue==[] and pipeline.payments==[]


def test_shadow_g13_is_persisted_for_real_run_artifacts(pipeline):
    from datetime import datetime,timezone
    from app.domain.mandates import AgentIdentity,AutonomyPolicy,AutonomyRun,Mandate
    mid=pipeline.create(['price-one'])
    with SessionLocal() as s:
        policy=AutonomyPolicy(name='shadow-test-'+uuid.uuid4().hex,enabled=False,version='autonomy-policy-v0',mandate_template={},acquisition_mode='TELEGRAPH_HTTP',allow_telegraph_http=True,allow_erc8183=False,allow_anchor=False,strict_verification=True,read_only_replay=False,cadence_seconds=900,dedupe_window_seconds=900,max_usdc_per_run=Decimal('0.01'),max_usdc_per_day=Decimal('0.03'),max_runs_per_day=3,max_concurrent_runs=1,state='DRAFT')
        s.add(policy);s.flush()
        identity=AgentIdentity(agent_id=str(uuid.uuid4()),origin='INTERNAL_AUTONOMY',status='ACTIVE',policy_id=policy.policy_id,name='Synthetic shadow agent')
        s.add(identity);s.flush()
        run=AutonomyRun(policy_id=policy.policy_id,agent_identity_id=identity.agent_id,scheduled_for=datetime.now(timezone.utc),idempotency_key=uuid.uuid4().hex,state='COMPLETED',planned_cost_usdc=Decimal('0.01'),actual_cost_usdc=Decimal('0'),mandate_id=mid)
        s.add(run);s.flush()
        mandate=s.get(Mandate,mid);mandate.agent_identity_id=identity.agent_id;mandate.autonomy_run_id=run.run_id
        s.commit()
    pipeline.drain()
    with SessionLocal() as s:
        checkpoints=s.query(PolicyEvaluation).filter_by(policy_subject_id=mid,policy_id='AUTHORITY_SHADOW_CDG').all()
        assert checkpoints and all(x.result in {'CONTINUE','THROTTLE','REVIEW','HALT'} for x in checkpoints)
        assert any(x.result_core['details']['run_id']==run.run_id for x in checkpoints)
        assert s.query(PolicyEvaluation).filter_by(policy_type='STRUCTURAL_AUTONOMY',policy_subject_id=identity.agent_id).count()>0
