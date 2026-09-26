"""Record delivery only after the final successful ASGI response send."""
import json
import logging
import uuid

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.persistence.database import SessionLocal
from app.tickets.disclosure import delivered
from app.tickets.public_identity import ticket_by_hash

logger = logging.getLogger(__name__)


def record_consumer_delivery(mandate_id, acquisition_ids, evidence_ids):
    from app.api.consumer_result import DELIVERY_EVENT
    from app.domain.mandates import UsageEvent
    with SessionLocal() as session:
        session.add(UsageEvent(
            mandate_id=mandate_id, event_type=DELIVERY_EVENT,
            metadata_={"origin": "M2M", "acquisition_ids": acquisition_ids,
                       "evidence_ids": evidence_ids,
                       "delivery_surface": "x402-public-result",
                       "delivery_scope": "SERVER_DELIVERY_CONFIRMED"},
        ))
        session.commit()


class ConsumerResultResponse(JSONResponse):
    """Append one receipt per successful send, never a consumer acknowledgment.

    Socket send and DB commit cannot be atomic. Missing receipts remain UNKNOWN;
    retries append another delivery observation, without replaying any payment.
    """
    def __init__(self, content, **kwargs):
        super().__init__(content, **kwargs)
        result = content["consumer_result"]
        self.delivery = None
        if result["status"] == "DELIVERED" and result["results"]:
            self.delivery = (content["mandate_id"],
                             sorted({r["acquisition_id"] for r in result["results"]}),
                             sorted({r["evidence_id"] for r in result["results"]}))

    async def __call__(self, scope, receive, send):
        await super().__call__(scope, receive, send)
        if self.delivery:
            try:
                await run_in_threadpool(record_consumer_delivery, *self.delivery)
            except Exception:
                logger.error("M2M_CONSUMER_DELIVERY_AUDIT_UNAVAILABLE")


def record_delivery(response_hash, context_id, request_id):
    with SessionLocal() as session:
        ticket = ticket_by_hash(session, response_hash)
        if ticket is not None:
            delivered(session, ticket, context_id, request_id)
            session.commit()


class DisclosureMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        m2m = path.startswith(("/v1/m2m/mandates", "/v1/m2m/tickets/"))
        receipt = path.startswith("/v1/titular-check/")
        status, body = 0, bytearray()

        async def audited_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                if receipt:
                    headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in (b"cache-control", b"x-robots-tag")]
                    message = {**message, "headers": headers + [(b"cache-control", b"no-store"), (b"x-robots-tag", b"noindex, nofollow, noarchive")]}
            if m2m and message["type"] == "http.response.body" and 200 <= status < 300:
                body.extend(message.get("body", b""))
            await send(message)
            if m2m and message["type"] == "http.response.body" and not message.get("more_body", False) and 200 <= status < 300:
                result = json.loads(body)
                contract = result.get("titular_check", {})
                if contract.get("status") == "AVAILABLE":
                    from app.api.m2m import _m2m_context_id
                    authorization = dict(scope.get("headers", [])).get(b"authorization", b"").decode()
                    context = _m2m_context_id(authorization.partition(" ")[2])
                    try:
                        await run_in_threadpool(record_delivery, contract["response_hash"], context, str(uuid.uuid4()))
                    except Exception:
                        # A socket send and DB commit cannot be atomic. Never turn
                        # an uncertain send into an invented successful delivery.
                        logger.error("TITULAR_CHECK_DELIVERY_AUDIT_UNAVAILABLE")
        await self.app(scope, receive, audited_send)
