"""Turnstile server validation and short-lived, receipt-bound access grants."""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import timedelta
from urllib.request import Request as URLRequest, urlopen
from urllib.error import URLError
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func, text

from app.domain.mandates import UsageEvent
from app.tickets.disclosure import append_event, utcnow


def configuration():
    key = os.environ.get("TURNSTILE_SITE_KEY", "")
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "")
    signing = os.environ.get("TITULAR_CHECK_SESSION_SECRET", "")
    hosts = set(filter(None, os.environ.get("TITULAR_CHECK_ALLOWED_HOSTS", "").split(",")))
    if not key or not secret or len(signing) < 32 or not hosts:
        raise HTTPException(503, "HUMAN_PRESENCE_UNCONFIGURED")
    return key, secret, signing, hosts


def request_facts(request):
    _, _, secret, _ = configuration()
    # Do not trust client-supplied X-Forwarded-For. Configure the ASGI server's
    # trusted proxy addresses at deployment; shared proxy IPs fail conservatively.
    peer = request.client.host if request.client else "unknown"
    return {
        "ip_hmac": hmac.new(secret.encode(), ("ip:" + peer).encode(), hashlib.sha256).hexdigest(),
        "user_agent_hash": hashlib.sha256(request.headers.get("user-agent", "").encode()).hexdigest(),
    }


def require_origin(request):
    _, _, _, hosts = configuration()
    origin = urlparse(request.headers.get("origin", ""))
    if origin.scheme != "https" or origin.hostname not in hosts:
        raise HTTPException(403, "RECEIPT_ORIGIN_INVALID")


def limit_access(session, request, response_hash):
    facts = request_facts(request)
    now = utcnow()
    # Transaction locks serialize counters across workers without external Redis.
    if session.get_bind().dialect.name == "postgresql":
        for key in sorted(["ip:" + facts["ip_hmac"], "hash:" + response_hash]):
            lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    base = session.query(func.count(UsageEvent.event_id)).filter(
        UsageEvent.event_type == "TITULAR_CHECK_ACCESS_ATTEMPT",
        UsageEvent.created_at >= now - timedelta(seconds=60),
    )
    for field, value, cap in (("ip_hmac", facts["ip_hmac"], 60), ("response_hash", "0x" + response_hash, 120)):
        column = UsageEvent.metadata_["metadata"][field] if field == "ip_hmac" else UsageEvent.metadata_[field]
        if base.filter(column.as_string() == value).scalar() >= cap:
            raise HTTPException(429, "RECEIPT_RATE_LIMITED")
    append_event(session, "TITULAR_CHECK_ACCESS_ATTEMPT", response_hash=response_hash,
                 source="PUBLIC_ACCESS", metadata=facts)
    session.commit()
    return facts


def siteverify(token):
    _, secret, _, _ = configuration()
    body = json.dumps({"secret": secret, "response": token}).encode()
    request = URLRequest("https://challenges.cloudflare.com/turnstile/v0/siteverify", data=body,
                         headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=10) as result:
            return json.loads(result.read(16384))
    except (URLError, TimeoutError, ValueError):
        raise HTTPException(503, "HUMAN_PRESENCE_UNAVAILABLE") from None


def validate_challenge(token, response_hash):
    _, _, _, hosts = configuration()
    result = siteverify(token)
    if not isinstance(result, dict) or result.get("success") is not True or result.get("hostname") not in hosts or result.get("action") != "titular_check" or result.get("cdata") != response_hash:
        raise HTTPException(403, "HUMAN_PRESENCE_REJECTED")


def grant(response_hash, facts):
    _, _, secret, _ = configuration()
    claims = {"hash": response_hash, "session_id": str(uuid.uuid4()), "exp": int(time.time()) + 900, **facts}
    encoded = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()).decode()
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature, claims


def require_grant(request, response_hash):
    _, _, secret, _ = configuration()
    token = request.headers.get("authorization", "").removeprefix("Bearer ")
    try:
        if len(token) > 4096: raise ValueError()
        encoded, signature = token.split(".")
        expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(encoded))
        facts = request_facts(request)
        if claims["exp"] <= time.time() or claims["hash"] != response_hash or any(claims[k] != v for k, v in facts.items()): raise ValueError()
        return claims
    except (ValueError, KeyError, TypeError):
        raise HTTPException(403, "HUMAN_PRESENCE_REQUIRED") from None
