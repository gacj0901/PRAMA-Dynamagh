import pytest
import redis
from starlette.requests import Request
from fastapi import HTTPException
from app.users import auth


def test_auth_limiter_fails_closed_on_redis_outage(monkeypatch):
    monkeypatch.setenv('REDIS_URL','redis://synthetic.invalid')
    def fail(*a,**k):raise redis.ConnectionError()
    monkeypatch.setattr(auth.redis,'from_url',fail)
    with pytest.raises(HTTPException) as e:auth.auth_rate_limit(Request({'type':'http','headers':[],'client':('test',1)}),'synthetic@example.invalid')
    assert e.value.status_code==503


def test_auth_limiter_is_bounded_without_forwarding_header_trust(monkeypatch):
    monkeypatch.setenv('REDIS_URL','redis://synthetic.invalid')
    class Client:
        def eval(self,*a):return 31
    monkeypatch.setattr(auth.redis,'from_url',lambda *a:Client())
    with pytest.raises(HTTPException) as e:auth.auth_rate_limit(Request({'type':'http','headers':[(b'x-forwarded-for',b'spoofed')],'client':('test',1)}),'synthetic@example.invalid')
    assert e.value.status_code==429
