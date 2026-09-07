import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
import redis
from fastapi import Depends, HTTPException, Request
from app.persistence.database import get_session
from app.redis_config import redis_url
from app.users.models import UserIdentity, UserSession

COOKIE='__Host-prama_session'
ITERATIONS=600_000


def enabled():return os.environ.get('USER_ONBOARDING_ENABLED','false').lower()=='true'


def require_enabled():
    if not enabled():raise HTTPException(503,'USER_ONBOARDING_UNAVAILABLE')


def normalize_email(value):
    value=value.strip().lower()
    if len(value)>254 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}',value):raise HTTPException(422,'EMAIL_INVALID')
    return value


def password_hash(password,salt=None):
    if not 12<=len(password)<=128:raise HTTPException(422,'PASSWORD_LENGTH_12_TO_128')
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex()
    return f'pbkdf2-sha256${ITERATIONS}${salt}${digest}'


def password_matches(password,encoded):
    if not 12<=len(password)<=128:return False
    try:
        algorithm,iterations,salt,expected=encoded.split('$')
        if algorithm!='pbkdf2-sha256' or int(iterations)!=ITERATIONS:return False
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),ITERATIONS).hex()
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError):return False


def auth_rate_limit(request,email):
    # Separate from the existing public spend quota. No forwarding header trust.
    peer=request.client.host if request.client else 'unknown'
    try:
        client=redis.from_url(redis_url())
        for kind,value,limit in [('peer',peer,30),('email',email,10)]:
            key='prama:users:auth:'+kind+':'+hashlib.sha256(value.encode()).hexdigest()
            count=client.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n",1,key,900)
            if int(count)>limit:raise HTTPException(429,'AUTH_RATE_LIMITED')
    except (KeyError,ValueError,redis.RedisError):raise HTTPException(503,'AUTH_RATE_LIMIT_UNAVAILABLE') from None


def check_origin(request):
    origin=request.headers.get('origin')
    allowed=set(os.environ.get('USER_WEB_ORIGINS','https://prama-dynamagh.up.railway.app').split(','))
    if origin and origin not in allowed:raise HTTPException(403,'ORIGIN_NOT_ALLOWED')


def token_from(request):
    header=request.headers.get('authorization','')
    if header.startswith('Bearer '):return header[7:]
    if request.method not in {'GET','HEAD','OPTIONS'}:check_origin(request)
    return request.cookies.get(COOKIE,'')


def current_user(request:Request,session=Depends(get_session)):
    token=token_from(request)
    if not token or len(token)>256:raise HTTPException(401,'SESSION_REQUIRED')
    row=session.get(UserSession,hashlib.sha256(token.encode()).hexdigest())
    now=datetime.now(timezone.utc)
    if row is None or row.revoked_at or row.expires_at<=now:raise HTTPException(401,'SESSION_INVALID')
    user=session.get(UserIdentity,row.user_id)
    if user is None or user.status!='ACTIVE':raise HTTPException(401,'SESSION_INVALID')
    return user


def new_session(session,user,response):
    token=secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=user.user_id,expires_at=datetime.now(timezone.utc)+timedelta(days=7)))
    response.set_cookie(COOKIE,token,max_age=604800,secure=True,httponly=True,samesite='strict',path='/')
    response.headers['Cache-Control']='no-store'
    return token


def protect_user_artifact(request:Request,session=Depends(get_session)):
    """Keep anonymous artifacts public; private USER artifacts require ownership."""
    from app.domain.mandates import Mandate, Ticket
    mid=request.path_params.get('mandate_id')
    tid=request.path_params.get('ticket_id')
    if not mid and tid:
        ticket=session.get(Ticket,tid)
        mid=ticket.mandate_id if ticket else None
    if not mid:return
    mandate=session.get(Mandate,mid)
    if mandate and mandate.origin=='USER':
        user=current_user(request,session)
        if user.user_id!=mandate.actor_id:raise HTTPException(404,'MANDATE_MISSING')
