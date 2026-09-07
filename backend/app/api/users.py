"""Additive email onboarding and user-scoped internal credit."""
import hashlib
import json
import uuid
from datetime import datetime,timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text as sql
from app.persistence.database import get_session
from app.domain.mandates import Mandate, AcquisitionTask, MandateTransition, UsageEvent, Ticket, Evidence, Decision, TelegraphCall
from app.users import auth,credit
from app.users.history_archive import cleanup_expired, write_archive
from app.users.models import UserIdentity, UserSession, UserCreditAccount, UserCreditLedger, UserMandate
from app.public_safety import MAX_SINGLE_ACQUISITION_USDC, public_max_mandate_usdc, enforce_public_rate_limit, _reserve_spend
from app.workers.tasks import execute_acquisition

router=APIRouter(prefix='/v1/users',tags=['users'])
DUMMY_PASSWORD_HASH=auth.password_hash('non-account-timing-value','00'*16)


class Credentials(BaseModel):
    email:str=Field(min_length=3,max_length=254)
    password:SecretStr


class UserMandateInput(BaseModel):
    text:str=Field(min_length=1,max_length=20_000)
    max_budget_usdc:Decimal=Field(default=Decimal('0.01'),gt=0,le=Decimal('0.01'),max_digits=18,decimal_places=6)


def user_json(user):return {'user_id':user.user_id,'email':user.email,'status':user.status,'created_at':user.created_at}


def credit_json(session,uid):return {k:f'{v:.6f}' for k,v in credit.balance(session,uid).items()}


@router.get('/status')
def module_status(session=Depends(get_session)):
    guards=[]
    try:
        guards=list(session.execute(sql("SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relname='user_credit_ledger' AND n.nspname=current_schema() AND t.tgenabled='O' AND NOT t.tgisinternal")).scalars())
    except Exception:session.rollback()
    ready={'user_credit_no_mutation','user_credit_no_truncate','user_credit_balance_guard'}.issubset(guards)
    return {'enabled':auth.enabled() and ready,'welcome_credit':f'{credit.welcome_amount():.6f}','account_model':'INTERNAL_CREDIT','email_verification':False,'ledger_guards_installed':ready}


@router.post('/register')
def register(payload:Credentials,request:Request,response:Response,session=Depends(get_session)):
    auth.require_enabled();auth.check_origin(request)
    email=auth.normalize_email(payload.email);auth.auth_rate_limit(request,email)
    password=payload.password.get_secret_value()
    encoded=auth.password_hash(password)
    user=session.query(UserIdentity).filter_by(email=email).one_or_none()
    if user is None:
        try:
            with session.begin_nested():
                user=UserIdentity(email=email,password_hash=encoded)
                session.add(user);session.flush()
                session.add(UserCreditAccount(user_id=user.user_id));session.flush()
                credit.grant_welcome(session,user.user_id)
        except IntegrityError:
            user=session.query(UserIdentity).filter_by(email=email).one_or_none()
            if user is None:raise HTTPException(503,'REGISTRATION_UNAVAILABLE') from None
    if user.status!='ACTIVE' or not auth.password_matches(password,user.password_hash):raise HTTPException(401,'CREDENTIALS_INVALID')
    # A repeated request authenticates the same identity; it never resets credentials.
    welcome=credit.grant_welcome(session,user.user_id)
    token=auth.new_session(session,user,response)
    session.commit()
    return {'user':user_json(user),'session_token':token,'credit':credit_json(session,user.user_id),'welcome_credit_amount':f'{welcome.amount:.6f}'}


@router.post('/login')
def login(payload:Credentials,request:Request,response:Response,session=Depends(get_session)):
    auth.require_enabled();auth.check_origin(request)
    email=auth.normalize_email(payload.email);auth.auth_rate_limit(request,email)
    user=session.query(UserIdentity).filter_by(email=email).one_or_none()
    # Equal KDF work for an unknown email without storing any fake account.
    encoded=user.password_hash if user else DUMMY_PASSWORD_HASH
    valid=auth.password_matches(payload.password.get_secret_value(),encoded)
    if not user or not valid or user.status!='ACTIVE':raise HTTPException(401,'CREDENTIALS_INVALID')
    token=auth.new_session(session,user,response);session.commit()
    return {'user':user_json(user),'session_token':token}


@router.post('/logout')
def logout(request:Request,response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    token=auth.token_from(request)
    row=session.get(UserSession,hashlib.sha256(token.encode()).hexdigest());row.revoked_at=datetime.now(timezone.utc)
    session.commit();response.delete_cookie(auth.COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    return {'signed_out':True}


@router.get('/me/credit')
def my_credit(response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    response.headers['Cache-Control']='no-store'
    return {'user':user_json(user),**credit_json(session,user.user_id)}


@router.get('/me/credit/events')
def my_credit_events(response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    response.headers['Cache-Control']='no-store'
    return [{'event_id':r.event_id,'event_type':r.event_type,'amount':f'{r.amount:.6f}','mandate_id':r.mandate_id,'acquisition_id':r.acquisition_id,'idempotency_key':r.idempotency_key,'created_at':r.created_at} for r in session.query(UserCreditLedger).filter_by(user_id=user.user_id).order_by(UserCreditLedger.created_at,UserCreditLedger.event_id)]


def create_user_mandate(session,user,text,budget,request_key):
    if not text.strip():raise HTTPException(422,'QUERY_REQUIRED')
    cap=min(MAX_SINGLE_ACQUISITION_USDC,public_max_mandate_usdc())
    if not budget.is_finite() or budget<=0 or budget>cap or budget.as_tuple().exponent < -6:raise HTTPException(422,'USER_REQUEST_BUDGET_EXCEEDED')
    request_hash=hashlib.sha256(json.dumps({'text':text,'budget':f'{budget:.6f}'},sort_keys=True).encode()).hexdigest()
    credit.lock_account(session,user.user_id)
    previous=session.query(UserMandate).filter_by(user_id=user.user_id,request_key=request_key).one_or_none()
    if previous:
        if previous.request_hash!=request_hash:raise HTTPException(409,'REQUEST_IDEMPOTENCY_CONFLICT')
        m=session.get(Mandate,previous.mandate_id)
        task=session.query(AcquisitionTask).filter_by(mandate_id=m.mandate_id).one()
        return m,task
    m=Mandate(actor_id=user.user_id,text=text,max_budget_usdc=budget,status='RECEIVED',origin='USER')
    session.add(m);session.flush()
    session.add(UserMandate(mandate_id=m.mandate_id,user_id=user.user_id,request_key=request_key,request_hash=request_hash));session.flush()
    credit.reserve(session,user.user_id,m.mandate_id,budget)
    # Same PostgreSQL transaction, same atomic G12 function and shared daily row.
    _reserve_spend(session,m.mandate_id,budget,cap,'USER')
    task=AcquisitionTask(mandate_id=m.mandate_id,query=text,required=True,status='QUEUED',ordinal=0)
    session.add(task);session.flush()
    session.add_all([MandateTransition(mandate_id=m.mandate_id,from_status=None,to_status='RECEIVED',reason='authenticated user request'),UsageEvent(mandate_id=m.mandate_id,event_type='MANDATE_CREATED',metadata_={'origin':'USER'}),UsageEvent(mandate_id=m.mandate_id,acquisition_id=task.acquisition_id,event_type='ACQUISITION_QUEUED',metadata_={'origin':'USER'})])
    return m,task


def mandate_json(session,m):
    ticket=session.query(Ticket).filter_by(mandate_id=m.mandate_id).first()
    decision=session.query(Decision).filter_by(mandate_id=m.mandate_id).first()
    return {'mandate_id':m.mandate_id,'text':m.text,'status':m.status,'budget':f'{m.max_budget_usdc:.6f}','created_at':m.created_at,'decision':decision.state if decision else None,'ticket_id':ticket.ticket_id if ticket else None,'ticket_hash':ticket.ticket_hash if ticket else None}


def _selection_telemetry(task, call, evidence):
    requested = task.requested_intent
    resolved = call.intent if call else None
    return {
        'acquisition_id': task.acquisition_id,
        'status': task.status,
        'requested_intent': requested,
        'resolved_intent': resolved,
        'service': (call.miner_name or call.miner_id) if call else 'Telegraph upstream (sin respuesta)',
        'miner_id': call.miner_id if call else None,
        'miner_name': call.miner_name if call else None,
        'signal_hash': call.signal_hash if call else None,
        'cost_usdc': f'{call.cost_usd:.6f}' if call and call.cost_usd is not None else None,
        'duration_ms': call.duration_ms if call else None,
        'reasoning': call.reasoning if call else None,
        'warnings': call.warnings if call else [],
        'provenance_status': evidence.provenance_status if evidence else None,
        'admissibility': evidence.admissibility if evidence else None,
        'selection_rationale': {
            'routing': 'TELEGRAPH_UPSTREAM_INTENT_ROUTING',
            'explanation': (
                'El Gateway envió la consulta a Telegraph y conserva el minero '
                'que Telegraph devolvió para esa intención. No existe un ranking '
                'local ni una selección manual de mineros en PRAMA-Dynamagh.'
            ),
            'requested_intent': requested,
            'resolved_intent': resolved,
            'proof_fields': ['miner_id', 'miner_name', 'signal_hash', 'provenance_status', 'cost_usdc', 'duration_ms'],
        },
    }


def user_detail_json(session, m):
    detail = mandate_json(session, m)
    tasks = session.query(AcquisitionTask).filter_by(mandate_id=m.mandate_id).order_by(AcquisitionTask.ordinal, AcquisitionTask.acquisition_id).all()
    calls = {c.acquisition_id: c for c in session.query(TelegraphCall).filter_by(mandate_id=m.mandate_id)}
    evidence = {e.acquisition_id: e for e in session.query(Evidence).filter_by(mandate_id=m.mandate_id)}
    detail['acquisitions'] = [_selection_telemetry(t, calls.get(t.acquisition_id), evidence.get(t.acquisition_id)) for t in tasks]
    detail['state_transitions'] = [
        {'from': row.from_status, 'to': row.to_status, 'reason': row.reason, 'created_at': row.created_at}
        for row in session.query(MandateTransition).filter_by(mandate_id=m.mandate_id).order_by(MandateTransition.created_at, MandateTransition.transition_id)
    ]
    detail['results'] = [
        {'evidence_id': e.evidence_id, 'admissibility': e.admissibility, 'result': e.normalized_payload.get('result', e.normalized_payload)}
        for e in sorted(evidence.values(), key=lambda item: item.evidence_id)
    ]
    return detail


@router.post('/me/mandates',status_code=202)
def submit(payload:UserMandateInput,request:Request,response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    auth.require_enabled();enforce_public_rate_limit(request)
    key=request.headers.get('idempotency-key') or str(uuid.uuid4())
    if not 1<=len(key)<=128:raise HTTPException(422,'REQUEST_KEY_INVALID')
    try:
        m,task=create_user_mandate(session,user,payload.text,payload.max_budget_usdc,key)
        session.commit()
    except HTTPException:
        session.rollback();raise
    except Exception:
        session.rollback();raise HTTPException(503,'USER_SPEND_AUTHORIZATION_UNAVAILABLE') from None
    # Re-dispatch is safe after a lost HTTP response or a broker outage. Durable
    # task ownership, credit idempotency and the existing payment claim apply.
    if task.status in {'QUEUED','PENDING'}:
        try:execute_acquisition.delay(m.mandate_id,task.acquisition_id)
        except Exception:raise HTTPException(503,'REQUEST_QUEUED_RETRY_SAME_KEY') from None
    response.headers['Cache-Control']='no-store'
    return {**mandate_json(session,m),'request_key':key}


@router.get('/me/mandates')
def history(response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    response.headers['Cache-Control']='no-store'
    return [mandate_json(session,m) for m in session.query(Mandate).join(UserMandate,UserMandate.mandate_id==Mandate.mandate_id).filter(UserMandate.user_id==user.user_id).order_by(Mandate.created_at.desc()).limit(100)]


@router.get('/me/mandates/{mandate_id}')
def detail(mandate_id:str,response:Response,user=Depends(auth.current_user),session=Depends(get_session)):
    link=session.get(UserMandate,mandate_id)
    if not link or link.user_id!=user.user_id:raise HTTPException(404,'MANDATE_MISSING')
    response.headers['Cache-Control']='no-store'
    m=session.get(Mandate,mandate_id)
    evidence=session.query(Evidence).filter_by(mandate_id=mandate_id).all()
    return user_detail_json(session, m)


@router.get('/me/history/file')
def history_file(user=Depends(auth.current_user), session=Depends(get_session)):
    cleanup_expired()
    rows = session.query(Mandate).join(UserMandate, UserMandate.mandate_id == Mandate.mandate_id).filter(UserMandate.user_id == user.user_id).order_by(Mandate.created_at.desc()).limit(100).all()
    payload = {
        'archive_schema': 'prama.user.history.archive.v1',
        'user_id': user.user_id,
        'retention_seconds': 7200,
        'generated_at': datetime.now(timezone.utc),
        'entries': [user_detail_json(session, row) for row in rows],
    }
    path = write_archive(user.user_id, payload)
    return FileResponse(path, media_type='application/json', filename='prama-history-temporal.json', headers={'Cache-Control': 'private, max-age=7200'})
