"""Isolated PostgreSQL transactions, real API/auth, synthetic paid transport."""
import os
import sys
import json
import uuid
import threading
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import DBAPIError
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import app
from app.persistence.database import get_session
from app.users import auth,credit
from app.users.models import UserIdentity,UserSession,UserCreditLedger
from app.api import users
from app.domain.mandates import Mandate,AcquisitionTask,TelegraphCall,Ticket,PublicManualSpendLedger,PublicManualSpendReservation
from app.workers import acquisition,tasks
from app.authority import runtime


@pytest.fixture(scope='module')
def user_database():
    url=make_url(os.environ['DATABASE_URL']);assert url.host in {'localhost','127.0.0.1'}
    owner=create_engine(url);schema='users_'+uuid.uuid4().hex
    with owner.begin() as c:c.execute(text('CREATE SCHEMA '+schema))
    engine=create_engine(url.update_query_dict({'options':'-csearch_path='+schema}),pool_pre_ping=True)
    env=dict(os.environ,PGOPTIONS='-csearch_path='+schema)
    p=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=Path(__file__).resolve().parents[2],env=env,capture_output=True,text=True,timeout=40)
    assert p.returncode==0,p.stderr
    try:yield sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)
    finally:
        engine.dispose()
        with owner.begin() as c:c.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        owner.dispose()


class Response:
    status=200
    def __init__(self,data=None):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.data).encode()


@pytest.fixture
def flow(monkeypatch,user_database):
    monkeypatch.setenv('USER_ONBOARDING_ENABLED','true');monkeypatch.setenv('WELCOME_CREDIT_USDC','0.25')
    monkeypatch.setenv('GLOBAL_DAILY_SPEND_CAP_USDC','1.00');monkeypatch.setenv('PUBLIC_MAX_MANDATE_USDC','0.05');monkeypatch.setenv('GATEWAY_URL','http://gateway.test')
    monkeypatch.setattr(auth,'auth_rate_limit',lambda *a:None);monkeypatch.setattr(users,'enforce_public_rate_limit',lambda *a:None)
    for m in [tasks,acquisition,runtime]:monkeypatch.setattr(m,'SessionLocal',user_database)
    from app.persistence import database
    monkeypatch.setattr(database,'SessionLocal',user_database)
    def sessions():
        with user_database() as s:yield s
    app.dependency_overrides[get_session]=sessions
    queue=[];payments=[]
    monkeypatch.setattr(tasks.execute_acquisition,'delay',lambda mid,aid:queue.append((mid,aid)))
    class Locks:
        def set(self,*a,**k):return True
        def eval(self,*a,**k):return 1
    monkeypatch.setattr(tasks.redis,'from_url',lambda *a,**k:Locks())
    def gateway(request,**kwargs):
        body=json.loads(request.data);payments.append(body)
        if body['query']=='timeout':raise TimeoutError()
        return Response({'miner_id':'synthetic','intent':'CRYPTO_PRICE','signal_hash':'0x'+uuid.uuid4().hex,'payment':{'amount_usdc':'0.006000','network':'synthetic'},'cost_usd':'0.006000','result':{'value':'synthetic evidence'},'warnings':[]})
    monkeypatch.setattr(acquisition,'urlopen',gateway);monkeypatch.setattr(tasks,'urlopen',lambda *a,**k:Response())
    client=TestClient(app,base_url='https://testserver')
    password='synthetic-account-password'
    def register(email=None):
        email=email or uuid.uuid4().hex+'@example.invalid'
        r=client.post('/v1/users/register',json={'email':email,'password':password});assert r.status_code==200,r.text
        obj=r.json();return obj,{'Authorization':'Bearer '+obj['session_token']}
    def submit(headers,query='synthetic query',budget='0.01',key=None):
        return client.post('/v1/users/me/mandates',headers={**headers,'Idempotency-Key':key or uuid.uuid4().hex},json={'text':query,'max_budget_usdc':budget})
    def drain():
        while queue:tasks.execute_acquisition(*queue.pop(0))
    yield SimpleNamespace(client=client,register=register,submit=submit,drain=drain,queue=queue,payments=payments,factory=user_database,password=password)
    client.close();app.dependency_overrides.clear()


def test_registration_normalizes_email_and_grants_exactly_once(flow,monkeypatch):
    assert flow.client.get('/v1/users/status').json()['ledger_guards_installed'] is True
    email=uuid.uuid4().hex+'@example.invalid'
    first,headers=flow.register(' '+email.upper()+' ')
    monkeypatch.setenv('WELCOME_CREDIT_USDC','0.50')
    second,_=flow.register(email)
    assert first['user']['user_id']==second['user']['user_id'] and second['credit']['available_credit']=='0.250000'
    assert flow.client.get('/v1/users/me/credit',headers=headers).json()['total_credit']=='0.250000'
    with flow.factory() as s:
        rows=s.query(UserCreditLedger).filter_by(user_id=first['user']['user_id']).all()
        assert len(rows)==1 and rows[0].event_type=='WELCOME_CREDIT'
        assert s.query(UserSession).filter_by(token_hash=first['session_token']).count()==0
        assert s.get(UserIdentity,first['user']['user_id']).password_hash!=flow.password


def test_existing_email_cannot_reset_password_or_get_another_account(flow):
    obj,_=flow.register();email=obj['user']['email']
    r=flow.client.post('/v1/users/register',json={'email':email,'password':'different-account-password'})
    assert r.status_code==401
    assert flow.client.post('/v1/users/login',json={'email':email,'password':flow.password}).status_code==200


def test_session_cookie_revocation_expiry_and_origin(flow):
    obj,headers=flow.register()
    r=flow.client.post('/v1/users/login',json={'email':obj['user']['email'],'password':flow.password})
    cookie=r.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ['secure','httponly','samesite=strict','path=/'])
    blocked=flow.client.post('/v1/users/register',headers={'Origin':'https://foreign.invalid'},json={'email':'new@example.invalid','password':flow.password})
    assert blocked.status_code==403
    assert flow.client.post('/v1/users/logout',headers=headers).status_code==200
    assert flow.client.get('/v1/users/me/credit',headers=headers).status_code==401
    obj,headers=flow.register()
    with flow.factory() as s:
        row=s.query(UserSession).filter_by(user_id=obj['user']['user_id']).first();row.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1);s.commit()
    assert flow.client.get('/v1/users/me/credit',headers=headers).status_code==401


def test_real_pipeline_settles_credit_releases_surplus_and_retries_once(flow):
    obj,headers=flow.register();uid=obj['user']['user_id'];key=uuid.uuid4().hex
    r=flow.submit(headers,key=key);assert r.status_code==202,r.text
    mid=r.json()['mandate_id'];first=flow.queue[0]
    assert flow.client.get('/v1/users/me/credit',headers=headers).json()['reserved_credit']=='0.010000'
    flow.drain();tasks.execute_acquisition(*first)
    repeated=flow.submit(headers,key=key);assert repeated.json()['mandate_id']==mid
    assert len(flow.payments)==1
    c=flow.client.get('/v1/users/me/credit',headers=headers).json()
    assert (c['available_credit'],c['reserved_credit'],c['spent_credit'])==('0.244000','0.000000','0.006000')
    events=flow.client.get('/v1/users/me/credit/events',headers=headers).json()
    assert {e['event_type']:e['amount'] for e in events}=={'WELCOME_CREDIT':'0.250000','SPEND_RESERVATION':'0.010000','SPEND_SETTLEMENT':'0.006000','RESERVATION_RELEASE':'0.004000'}
    with flow.factory() as s:
        m=s.get(Mandate,mid);assert m.actor_id==uid and m.origin=='USER'
        ticket=s.query(Ticket).filter_by(mandate_id=mid).one()
        from app.tickets.service import verify
        assert verify(s,ticket)['status']=='VALID'
        assert s.get(PublicManualSpendReservation,mid).actual_spend_usdc==Decimal('.006')
        tid=ticket.ticket_id
    assert flow.client.get('/v1/tickets/'+tid+'/verify',headers=headers).json()['status']=='VALID'
    assert flow.client.get('/v1/mandates/'+mid+'/replay',headers=headers).json()['matches']
    conflict=flow.submit(headers,query='another query',key=key);assert conflict.status_code==409


def test_user_artifacts_are_private_and_anonymous_routes_stay_public(flow):
    first,a=flow.register();r=flow.submit(a);flow.drain();mid=r.json()['mandate_id']
    _,b=flow.register()
    assert flow.client.get('/v1/users/me/mandates',headers=b).json()==[]
    assert flow.client.get('/v1/users/me/mandates/'+mid,headers=b).status_code==404
    assert flow.client.get('/v1/mandates/'+mid,headers=b).status_code==404
    assert mid not in [m['mandate_id'] for m in flow.client.get('/v1/mandates').json()]
    with flow.factory() as s:
        m=Mandate(actor_id='anonymous-test',text='anonymous',max_budget_usdc=Decimal('.01'),origin='MANUAL');s.add(m);s.commit();anon=m.mandate_id
        tid=s.query(Ticket).filter_by(mandate_id=mid).one().ticket_id
    flow.client.cookies.clear()
    assert flow.client.get('/v1/mandates/'+mid).status_code==401
    assert flow.client.get('/v1/tickets/'+tid+'/verify').status_code==401
    assert flow.client.get('/v1/mandates/'+anon).status_code==200


def test_parallel_requests_cannot_overdraw_credit(flow,monkeypatch):
    monkeypatch.setenv('WELCOME_CREDIT_USDC','0.015')
    obj,_=flow.register();uid=obj['user']['user_id'];barrier=threading.Barrier(2)
    def reserve_one(i):
        with flow.factory() as s:
            u=s.get(UserIdentity,uid);barrier.wait()
            try:
                users.create_user_mandate(s,u,'parallel '+str(i),Decimal('.01'),str(i));s.commit();return 202
            except HTTPException as e:s.rollback();return e.status_code
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(reserve_one,range(2)))==[202,422]
    with flow.factory() as s:
        c=credit.balance(s,uid);assert c['available_credit']==Decimal('.005') and c['reserved_credit']==Decimal('.01')


def test_global_backstop_rolls_back_user_and_mandate_atomically(flow,monkeypatch):
    obj,headers=flow.register();monkeypatch.setenv('GLOBAL_DAILY_SPEND_CAP_USDC','0.005')
    r=flow.submit(headers);assert r.status_code==429
    with flow.factory() as s:
        assert s.query(Mandate).filter_by(actor_id=obj['user']['user_id']).count()==0
        assert s.query(UserCreditLedger).filter_by(user_id=obj['user']['user_id']).count()==1
    assert not flow.payments


def test_insufficient_credit_and_hard_per_acquisition_cap_reject(flow,monkeypatch):
    monkeypatch.setenv('WELCOME_CREDIT_USDC','0.004')
    _,h=flow.register()
    assert flow.submit(h).status_code==422
    assert flow.submit(h,budget='0.02').status_code==422
    assert not flow.queue and not flow.payments


@pytest.mark.parametrize('statement',['UPDATE user_credit_ledger SET amount=1 WHERE user_id=:uid','DELETE FROM user_credit_ledger WHERE user_id=:uid','TRUNCATE user_credit_ledger'])
def test_database_rejects_ledger_mutation(flow,statement):
    obj,_=flow.register()
    with flow.factory() as s:
        with pytest.raises(DBAPIError):s.execute(text(statement),{'uid':obj['user']['user_id']})
        s.rollback()
        assert credit.balance(s,obj['user']['user_id'])['available_credit']==Decimal('.25')


def test_unknown_payment_holds_user_and_global_reservations(flow):
    obj,h=flow.register();r=flow.submit(h,query='timeout');flow.drain()
    mid=r.json()['mandate_id']
    with flow.factory() as s:
        assert credit.balance(s,obj['user']['user_id'])['reserved_credit']==Decimal('.01')
        assert s.get(PublicManualSpendReservation,mid).status=='RESERVED'
        assert s.query(UserCreditLedger).filter_by(user_id=obj['user']['user_id'],event_type='SPEND_SETTLEMENT').count()==0


def test_known_unspent_failure_releases_user_credit(flow):
    obj,h=flow.register();r=flow.submit(h)
    with flow.factory() as s:
        task=s.query(AcquisitionTask).filter_by(mandate_id=r.json()['mandate_id']).one();task.query=' ';s.commit()
    flow.drain()
    with flow.factory() as s:
        c=credit.balance(s,obj['user']['user_id']);assert c['available_credit']==Decimal('.25') and c['reserved_credit']==0
        assert not flow.payments


def test_forged_ledger_insert_cannot_make_balance_negative(flow):
    obj,h=flow.register();r=flow.submit(h);mid=r.json()['mandate_id']
    with flow.factory() as s:
        with pytest.raises(DBAPIError):credit.append(s,obj['user']['user_id'],'RESERVATION_RELEASE',Decimal('.02'),uuid.uuid4().hex,mid)
        s.rollback();assert credit.balance(s,obj['user']['user_id'])['available_credit']==Decimal('.24')


def test_parallel_registration_grants_one_welcome(flow):
    email=uuid.uuid4().hex+'@example.invalid';barrier=threading.Barrier(2)
    def register_once(_):
        with TestClient(app,base_url='https://testserver') as client:
            barrier.wait();r=client.post('/v1/users/register',json={'email':email,'password':flow.password})
            assert r.status_code==200,r.text
            return r.json()['user']['user_id']
    with ThreadPoolExecutor(2) as pool:ids=list(pool.map(register_once,range(2)))
    assert ids[0]==ids[1]
    with flow.factory() as s:assert s.query(UserCreditLedger).filter_by(user_id=ids[0]).count()==1


def test_settlement_failure_rolls_back_user_events_and_keeps_uncertain_hold(flow,monkeypatch):
    obj,h=flow.register();r=flow.submit(h)
    def fail(*a,**k):raise RuntimeError('synthetic settlement failure')
    monkeypatch.setattr(acquisition,'settle_spend',fail)
    flow.drain()
    with flow.factory() as s:
        c=credit.balance(s,obj['user']['user_id']);assert c['reserved_credit']==Decimal('.01') and c['spent_credit']==0
        assert s.query(UserCreditLedger).filter_by(user_id=obj['user']['user_id']).count()==2
        call=s.query(TelegraphCall).filter_by(mandate_id=r.json()['mandate_id']).one()
        assert call.status=='PAYMENT_UNCERTAIN' and call.raw_response
