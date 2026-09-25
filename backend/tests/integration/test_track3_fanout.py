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
from app.domain.mandates import AcquisitionTask, TelegraphCall, Evidence, Decision, Ticket, PolicyEvaluation, PublicManualSpendReservation, PublicManualSpendLedger, UsageEvent
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
    monkeypatch.setenv('FULL_AUTONOMY_ENABLED','true')
    monkeypatch.setattr(api,'enforce_public_rate_limit',lambda request:None)
    locks=Locks();monkeypatch.setattr(tasks.redis,'from_url',lambda *a,**k:locks)
    queue=[];payments=[]
    monkeypatch.setattr(tasks.execute_acquisition,'delay',lambda mid,aid:queue.append((mid,aid)))
    def gateway(request,**kwargs):
        assert kwargs['timeout'] == acquisition.GATEWAY_REQUEST_TIMEOUT_SECONDS
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
    with SessionLocal() as s:
        s.add(UsageEvent(
            mandate_id=mid,
            acquisition_id=bad_id,
            event_type='ACQUISITION_PAYMENT_RECONCILED',
            metadata_={'settled':False,'actual_cost_usdc':'0.000000'},
        ))
        s.commit()
        assert acquisition.uncertain_hold(s,mid)==0


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


@pytest.mark.parametrize("composition_failure", [False, True])
def test_shadow_g13_is_persisted_for_real_run_artifacts(pipeline, monkeypatch, composition_failure):
    if composition_failure:
        def fail_composition(*args, **kwargs):
            raise ValueError("synthetic composition failure")
        monkeypatch.setattr(runtime, "run_pre_next_action_authority_check", fail_composition)
    from datetime import datetime,timedelta,timezone
    from app.domain.mandates import AgentAuthorityProfile,AgentIdentity,AutonomyPolicy,AutonomyRun,Mandate
    mid=pipeline.create(['price-one'])
    with SessionLocal() as s:
        policy=AutonomyPolicy(name='shadow-test-'+uuid.uuid4().hex,enabled=False,version='autonomy-policy-v0',mandate_template={},acquisition_mode='TELEGRAPH_HTTP',allow_telegraph_http=True,allow_erc8183=False,allow_anchor=False,strict_verification=True,read_only_replay=False,cadence_seconds=900,dedupe_window_seconds=900,max_usdc_per_run=Decimal('0.01'),max_usdc_per_day=Decimal('0.03'),max_runs_per_day=3,max_concurrent_runs=1,state='DRAFT')
        s.add(policy);s.flush()
        identity=AgentIdentity(agent_id=str(uuid.uuid4()),origin='INTERNAL_AUTONOMY',status='ACTIVE',policy_id=policy.policy_id,name='Synthetic shadow agent')
        s.add(identity);s.flush()
        from app.authority.profiles import compute_authority_hash
        profile=AgentAuthorityProfile(principal_id='track3-test-principal',agent_identity_id=identity.agent_id,version=1,created_by='pytest',status='ACTIVE',valid_from=datetime.now(timezone.utc)-timedelta(seconds=1),allowed_intents=[],allowed_action_kinds=[],economic_budget=Decimal('0.01'),per_action_budget=Decimal('0.01'),rolling_budget=None,concurrency_limit=1,cadence_policy=None,external_execution_allowed=True,telegraph_allowed=True,anchoring_allowed=False,erc8183_allowed=False,human_review_thresholds={},policy_version='agent-authority-v0');profile.authority_hash=compute_authority_hash(profile);s.add(profile);s.flush()
        run=AutonomyRun(policy_id=policy.policy_id,agent_identity_id=identity.agent_id,scheduled_for=datetime.now(timezone.utc),idempotency_key=uuid.uuid4().hex,state='COMPLETED',planned_cost_usdc=Decimal('0.01'),actual_cost_usdc=Decimal('0'),mandate_id=mid)
        s.add(run);s.flush()
        mandate=s.get(Mandate,mid);mandate.agent_identity_id=identity.agent_id;mandate.autonomy_run_id=run.run_id
        mandate.origin="AUTONOMOUS"
        mandate.autonomy_policy_id=policy.policy_id
        s.get(PublicManualSpendReservation,mid).origin="AUTONOMOUS"
        s.commit()
    pipeline.drain()
    with SessionLocal() as s:
        checkpoints=s.query(PolicyEvaluation).filter_by(policy_subject_id=mid,policy_id='AUTHORITY_SHADOW_CDG').all()
        assert checkpoints and all(x.result in {'CONTINUE','THROTTLE','REVIEW','HALT'} for x in checkpoints)
        assert any(x.result_core['details']['run_id']==run.run_id for x in checkpoints)
        assert s.query(PolicyEvaluation).filter_by(policy_type='STRUCTURAL_AUTONOMY',policy_subject_id=identity.agent_id).count()>0

        action = s.query(AcquisitionTask).filter_by(mandate_id=mid).one()
        assert len(pipeline.payments) == 0
        assert action.status == "FAILED"
        assert action.failure_code == ("AUTHORITY_COMPOSITION_RESTRICTED" if not composition_failure else "GATEWAY_UNAVAILABLE")
        assert s.query(Ticket).filter_by(mandate_id=mid).count() == 1
        if composition_failure:
            failure = s.query(PolicyEvaluation).filter_by(policy_subject_id=mid, policy_id="AUTHORITY_SHADOW_COMPOSITION").one()
            assert failure.result == "UNAVAILABLE"
            assert failure.result_core["enforcement"] == "SHADOW_ONLY"
        else:
            composed = s.query(PolicyEvaluation).filter_by(policy_type="AUTHORITY_COMPOSITION", policy_subject_id=action.acquisition_id).one()
            assert composed.result == "RESTRICT"
            assert composed.input_core["applicability"]["CD"] == "NOT_APPLICABLE"
            assert composed.result_core["enforcement"] == "SHADOW_ONLY"
            assert composed.input_core["g12"]["result"] == "PERMIT"
            longitudinal = s.query(PolicyEvaluation).filter_by(policy_type="STRUCTURAL_AUTONOMY", policy_subject_id=identity.agent_id).all()
            lineages = {row.input_core["trajectory_lineage_id"] for row in longitudinal}
            assert lineages <= {"o-agent-v0:" + identity.agent_id, "o-agent-v0:" + identity.agent_id + ":run:" + run.run_id}
            assert any(lineage.endswith(":run:" + run.run_id) for lineage in lineages)
            assert all(not row.input_core["integrity_violations"] for row in longitudinal)


def test_execution_permit_concurrent_consumption_is_postgres_one_shot(track3_database, monkeypatch):
    """Two independent PostgreSQL sessions authorize at most one dispatch."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from threading import Barrier, Lock

    from app.authority.delegated import (
        build_execution_action_material,
        consume_execution_permit,
        issue_execution_permit,
    )
    from app.authority.profiles import AuthorityProfileSpec, create_authority_profile
    from app.domain.mandates import AgentIdentity, AutonomyPolicy, Mandate

    monkeypatch.setenv("FULL_AUTONOMY_ENABLED", "true")
    monkeypatch.delenv("FULL_AUTONOMY_AGENT_ALLOWLIST", raising=False)
    session = track3_database()
    suffix = uuid.uuid4().hex
    agent_id = "permit-race-" + suffix
    mandate_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    policy = AutonomyPolicy(
        name="permit-race-" + suffix, enabled=False, version="autonomy-policy-v0",
        mandate_template={}, acquisition_mode="TELEGRAPH_HTTP", allow_telegraph_http=True,
        allow_erc8183=False, allow_anchor=False, strict_verification=True,
        read_only_replay=False, cadence_seconds=900, dedupe_window_seconds=900,
        max_usdc_per_run=Decimal("0.05"), max_usdc_per_day=Decimal("0.20"),
        max_runs_per_day=4, max_concurrent_runs=1, state="DRAFT",
    )
    try:
        session.add(policy)
        session.flush()
        identity = AgentIdentity(
            agent_id=agent_id, name="synthetic permit race", origin="INTERNAL_AUTONOMY",
            status="ACTIVE", autonomy_state="ACTIVE", policy_id=policy.policy_id,
        )
        session.add(identity)
        session.flush()
        profile = create_authority_profile(
            session,
            agent_id,
            AuthorityProfileSpec(
                valid_from=datetime.now(timezone.utc) - timedelta(seconds=1),
                total_budget_usdc=Decimal("0.05"),
                per_action_budget_usdc=Decimal("0.05"),
                allowed_action_kinds=["TELEGRAPH_HTTP_ACQUISITION"],
                external_execution_allowed=True,
                telegraph_allowed=True,
            ),
            created_by="pytest",
            principal_id="permit-race-principal",
        )
        mandate = Mandate(
            mandate_id=mandate_id, actor_id="permit-race-test", text="offline replay fixture",
            mandate_type="AUTONOMOUS", constraints={}, max_budget_usdc=Decimal("0.05"),
            status="ACQUIRING", origin="AUTONOMOUS", agent_identity_id=agent_id,
            autonomy_policy_id=policy.policy_id,
        )
        session.add(mandate)
        session.flush()
        action = build_execution_action_material(
            mandate_id=mandate_id,
            agent_identity_id=agent_id,
            action_id=action_id,
            action_kind="TELEGRAPH_HTTP_ACQUISITION",
            query="Synthetic no-network PostgreSQL permit race",
            requested_intent="RESEARCH_QUERY",
            causal_request_id=mandate_id,
            amount=Decimal("0.01"),
            adapter_target={
                "provider": "TEST_PROVIDER", "access_mechanism": "TEST",
                "adapter_kind": "tests.NoNetworkAdapter",
                "execution_target_fingerprint": "0x" + "1" * 64,
            },
            reservation={
                "mandate_id": mandate_id, "spend_date": "2026-09-24",
                "reserved_usdc": Decimal("0.05"), "status": "RESERVED", "origin": "AUTONOMOUS",
            },
        )
        permit = issue_execution_permit(
            session, mandate=mandate, action_id=action_id,
            action_kind="TELEGRAPH_HTTP_ACQUISITION", amount=Decimal("0.01"),
            g13_result="CONTINUE", action_material=action,
            constraints={"g12_reservation_verified": True},
        )
        permit_id = permit.permit_id
        session.commit()

        barrier = Barrier(2)
        dispatch_lock = Lock()
        authorized_dispatches = []

        def consume_once():
            own = track3_database()
            try:
                barrier.wait(timeout=10)
                def validate_identity(_permit):
                    current = own.query(AgentIdentity).filter_by(agent_id=agent_id).with_for_update().one()
                    if current.status != "ACTIVE" or current.autonomy_state != "ACTIVE":
                        raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")
                consume_execution_permit(
                    own,
                    permit_id,
                    expected_action_material=action,
                    authority_validator=validate_identity,
                )
                own.commit()
                with dispatch_lock:
                    authorized_dispatches.append("authorized")
                return "CONSUMED"
            except ValueError as error:
                own.rollback()
                return str(error)
            finally:
                own.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: consume_once(), range(2)))
        assert outcomes.count("CONSUMED") == 1
        assert outcomes.count("EXECUTION_PERMIT_ALREADY_CONSUMED") == 1
        assert len(authorized_dispatches) == 1
        with track3_database() as audit:
            from app.epistemic.contracts import canonical_hash
            commitments = audit.query(UsageEvent).filter_by(
                mandate_id=mandate_id,
                event_type="EXECUTION_DISPATCH_COMMITTED",
            ).all()
            assert len(commitments) == 1
            assert commitments[0].metadata_["commitment_state"] == "COMMITTED_FOR_DISPATCH"
            assert commitments[0].metadata_["action_envelope_hash"] == canonical_hash(action)
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize("authority_change", ["G13_HALT", "PROFILE_REVOKED", "G12_RELEASED"])
@pytest.mark.parametrize("change_order", ["BEFORE_COMMITMENT", "AFTER_COMMITMENT"])
def test_execution_commitment_orders_authority_changes_with_dispatch(
    track3_database, monkeypatch, authority_change, change_order,
):
    """PostgreSQL row locks order authority mutation against one-shot commitment."""
    from datetime import datetime, timedelta, timezone
    from threading import Event, Thread

    from app.authority.delegated import (
        build_execution_action_material,
        consume_execution_permit,
        issue_execution_permit,
        resolve_profile,
    )
    from app.authority.profiles import (
        AuthorityProfileSpec,
        create_authority_profile,
        set_authority_profile_status,
    )
    from app.domain.mandates import (
        AgentAuthorityProfile,
        AgentIdentity,
        AutonomyPolicy,
        Mandate,
        PublicManualSpendReservation,
    )
    from app.epistemic.contracts import canonical_hash
    from app.public_safety import release_spend_reservation

    monkeypatch.setenv("FULL_AUTONOMY_ENABLED", "true")
    monkeypatch.delenv("FULL_AUTONOMY_AGENT_ALLOWLIST", raising=False)
    session = track3_database()
    suffix = uuid.uuid4().hex
    agent_id = "commitment-race-" + suffix
    mandate_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    # Unique historical dates keep the daily-ledger primary key isolated per
    # race case without changing any runtime spend policy.
    spend_date = datetime(2000 + int(suffix[:2], 16), 1 + int(suffix[2:4], 16) % 12,
                          1 + int(suffix[4:6], 16) % 27, tzinfo=timezone.utc).date()
    policy = AutonomyPolicy(
        name="commitment-race-" + suffix, enabled=False, version="autonomy-policy-v0",
        mandate_template={}, acquisition_mode="TELEGRAPH_HTTP", allow_telegraph_http=True,
        allow_erc8183=False, allow_anchor=False, strict_verification=True,
        read_only_replay=False, cadence_seconds=900, dedupe_window_seconds=900,
        max_usdc_per_run=Decimal("0.05"), max_usdc_per_day=Decimal("0.20"),
        max_runs_per_day=4, max_concurrent_runs=1, state="DRAFT",
    )
    try:
        session.add(policy)
        session.flush()
        identity = AgentIdentity(
            agent_id=agent_id, name="synthetic commitment race", origin="INTERNAL_AUTONOMY",
            status="ACTIVE", autonomy_state="ACTIVE", policy_id=policy.policy_id,
        )
        session.add(identity)
        session.flush()
        profile = create_authority_profile(
            session, agent_id,
            AuthorityProfileSpec(
                valid_from=datetime.now(timezone.utc) - timedelta(seconds=1),
                total_budget_usdc=Decimal("0.05"), per_action_budget_usdc=Decimal("0.05"),
                allowed_action_kinds=["TELEGRAPH_HTTP_ACQUISITION"],
                external_execution_allowed=True, telegraph_allowed=True,
            ),
            created_by="pytest", principal_id="commitment-race-principal",
        )
        mandate = Mandate(
            mandate_id=mandate_id, actor_id="commitment-race-test", text="offline commitment fixture",
            mandate_type="AUTONOMOUS", constraints={}, max_budget_usdc=Decimal("0.05"),
            status="ACQUIRING", origin="AUTONOMOUS", agent_identity_id=agent_id,
            autonomy_policy_id=policy.policy_id,
        )
        session.add(mandate)
        session.flush()
        session.add(PublicManualSpendLedger(
            spend_date=spend_date, reserved_usdc=Decimal("0.05"), spent_usdc=Decimal("0"),
        ))
        session.add(PublicManualSpendReservation(
            mandate_id=mandate_id, spend_date=spend_date, reserved_usdc=Decimal("0.05"),
            actual_spend_usdc=Decimal("0"), status="RESERVED", origin="AUTONOMOUS",
        ))
        action = build_execution_action_material(
            mandate_id=mandate_id, agent_identity_id=agent_id, action_id=action_id,
            action_kind="TELEGRAPH_HTTP_ACQUISITION", query="No-network commitment race",
            requested_intent="RESEARCH_QUERY", causal_request_id=mandate_id,
            amount=Decimal("0.01"), adapter_target={
                "provider": "TEST_PROVIDER", "access_mechanism": "TEST",
                "adapter_kind": "tests.NoNetworkAdapter", "execution_target_fingerprint": "0x" + "2" * 64,
            },
            reservation={
                "mandate_id": mandate_id, "spend_date": spend_date.isoformat(),
                "reserved_usdc": Decimal("0.05"), "status": "RESERVED", "origin": "AUTONOMOUS",
            },
        )
        permit = issue_execution_permit(
            session, mandate=mandate, action_id=action_id,
            action_kind="TELEGRAPH_HTTP_ACQUISITION", amount=Decimal("0.01"),
            g13_result="CONTINUE", action_material=action,
            constraints={"g12_reservation_verified": True},
        )
        permit_id, profile_id = permit.permit_id, profile.authority_profile_id
        session.commit()

        def mutate_authority(own):
            if authority_change == "G13_HALT":
                current = own.query(AgentIdentity).filter_by(agent_id=agent_id).with_for_update().one()
                current.autonomy_state = "HALTED"
            elif authority_change == "PROFILE_REVOKED":
                set_authority_profile_status(
                    own, agent_id, profile_id, "REVOKED", created_by="pytest",
                    reason="ordered commitment race test",
                )
            else:
                release_spend_reservation(own, mandate_id, "AUTONOMOUS")

        def validate_fresh(own, _permit, started=None):
            if started is not None:
                started.set()
            current_identity = own.query(AgentIdentity).filter_by(agent_id=agent_id).with_for_update().one()
            current_profile = own.query(AgentAuthorityProfile).filter_by(
                authority_profile_id=profile_id,
            ).with_for_update().one()
            current_reservation = own.query(PublicManualSpendReservation).filter_by(
                mandate_id=mandate_id,
            ).with_for_update().one()
            try:
                effective = resolve_profile(own, agent_id)
            except ValueError as error:
                raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE") from error
            if (
                current_identity.status != "ACTIVE" or current_identity.autonomy_state != "ACTIVE"
                or effective.authority_profile_id != profile_id or current_profile.status != "ACTIVE"
                or current_reservation.status != "RESERVED"
            ):
                raise ValueError("EXECUTION_PERMIT_AUTHORITY_STALE")

        dispatches = []
        commitment_results = []
        if change_order == "BEFORE_COMMITMENT":
            mutation_held, release_mutation = Event(), Event()
            validation_started = Event()
            mutation_result = []

            def mutate_then_wait():
                own = track3_database()
                try:
                    mutate_authority(own)
                    mutation_held.set()
                    assert release_mutation.wait(timeout=10)
                    own.commit()
                    mutation_result.append("COMMITTED")
                finally:
                    own.close()

            def attempt_commit():
                own = track3_database()
                try:
                    consume_execution_permit(
                        own, permit_id, expected_action_material=action,
                        authority_validator=lambda row: validate_fresh(own, row, validation_started),
                    )
                    own.commit()
                    dispatches.append("AUTHORIZED")
                except ValueError as error:
                    own.rollback()
                    commitment_results.append(str(error))
                finally:
                    own.close()

            mutator = Thread(target=mutate_then_wait)
            worker = Thread(target=attempt_commit)
            mutator.start()
            assert mutation_held.wait(timeout=10)
            worker.start()
            assert validation_started.wait(timeout=10)
            release_mutation.set()
            mutator.join(timeout=10)
            worker.join(timeout=10)
            assert not mutator.is_alive() and not worker.is_alive()
            assert mutation_result == ["COMMITTED"]
            assert dispatches == []
            assert commitment_results == ["EXECUTION_PERMIT_AUTHORITY_STALE"]
        else:
            commitment_persisted, authority_changed = Event(), Event()

            def commit_then_dispatch():
                own = track3_database()
                try:
                    consume_execution_permit(
                        own, permit_id, expected_action_material=action,
                        authority_validator=lambda row: validate_fresh(own, row),
                    )
                    own.commit()
                    commitment_persisted.set()
                    assert authority_changed.wait(timeout=10)
                    dispatches.append("AUTHORIZED_BEST_EFFORT_DISPATCH")
                finally:
                    own.close()

            def mutate_after_commitment():
                own = track3_database()
                try:
                    assert commitment_persisted.wait(timeout=10)
                    mutate_authority(own)
                    own.commit()
                    authority_changed.set()
                finally:
                    own.close()

            worker = Thread(target=commit_then_dispatch)
            mutator = Thread(target=mutate_after_commitment)
            worker.start()
            mutator.start()
            worker.join(timeout=10)
            mutator.join(timeout=10)
            assert not worker.is_alive() and not mutator.is_alive()
            assert dispatches == ["AUTHORIZED_BEST_EFFORT_DISPATCH"]
            with track3_database() as audit:
                event = audit.query(UsageEvent).filter_by(
                    mandate_id=mandate_id, event_type="EXECUTION_DISPATCH_COMMITTED",
                ).one()
                assert event.metadata_["commitment_state"] == "COMMITTED_FOR_DISPATCH"
                assert event.metadata_["action_envelope_hash"] == canonical_hash(action)
    finally:
        session.rollback()
        session.close()
