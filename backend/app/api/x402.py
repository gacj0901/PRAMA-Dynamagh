"""Public x402 seller surface for inbound machine requests.

This module is deliberately a thin Access Plane boundary.  It exposes the
payment challenge and, after facilitator verification/settlement, hands the
request into the existing bounded M2M mandate pipeline.  It does not make
authority decisions and never calls Telegraph directly.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.identity import get_or_create_m2m_identity
from app.domain.mandates import (
    AcquisitionTask,
    Decision,
    Evidence,
    InboundX402Payment,
    Mandate,
    MandateStatus,
    MandateTransition,
    StructuralEvaluation,
    Ticket,
    UsageEvent,
)
from app.persistence.database import SessionLocal
from app.public_safety import reserve_m2m_spend
from app.workers.tasks import execute_acquisition


router = APIRouter(tags=["x402"])

PUBLIC_ORIGIN = os.environ.get("PUBLIC_BASE_URL", "https://prama-dynamagh.up.railway.app").rstrip("/")
X402_NETWORK = os.environ.get("X402_NETWORK", "eip155:84532")
X402_ASSET = os.environ.get("X402_ASSET", "0x036CbD53842c5426634e7929541eC2318f3dCF7e")
_BASE_SEPOLIA_USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
_BASE_SEPOLIA_USDC_DOMAIN = {"name": "USDC", "version": "2"}
X402_ASSET_NAME = os.environ.get("X402_ASSET_NAME")
X402_ASSET_VERSION = os.environ.get("X402_ASSET_VERSION")
X402_RECIPIENT = os.environ.get(
    "PRAMA_X402_RECIPIENT_ADDRESS",
    "0xC92b5ec74dca3EeE0A615dE026C3F3756cd18FB6",
)
X402_FACILITATOR = os.environ.get("X402_FACILITATOR_URL", "https://facilitator.payai.network").rstrip("/")
X402_AMOUNT_ATOMIC = os.environ.get("X402_PRICE_ATOMIC", "10000")
X402_AMOUNT_USDC = Decimal(X402_AMOUNT_ATOMIC) / Decimal("1000000")


def _eip712_domain() -> dict[str, str]:
    """Return the configured EIP-712 token domain for the exact EVM scheme.

    Base Sepolia USDC has a known protocol domain. Other assets must configure
    both values explicitly instead of inheriting USDC metadata by assumption.
    """
    if X402_ASSET_NAME and X402_ASSET_VERSION:
        return {"name": X402_ASSET_NAME, "version": X402_ASSET_VERSION}
    if bool(X402_ASSET_NAME) != bool(X402_ASSET_VERSION):
        raise RuntimeError("X402_EIP712_DOMAIN_INCOMPLETE")
    if X402_NETWORK == "eip155:84532" and X402_ASSET.lower() == _BASE_SEPOLIA_USDC.lower():
        return dict(_BASE_SEPOLIA_USDC_DOMAIN)
    raise RuntimeError("X402_EIP712_DOMAIN_REQUIRED")


def _requirements(resource: str | None = None) -> dict:
    return {
        "scheme": "exact",
        "network": X402_NETWORK,
        "asset": X402_ASSET,
        "amount": X402_AMOUNT_ATOMIC,
        "payTo": X402_RECIPIENT,
        "maxTimeoutSeconds": 300,
        "extra": _eip712_domain(),
        "resource": resource or f"{PUBLIC_ORIGIN}/v1/public/ask",
        "description": "Evidence-bound intelligence acquisition for autonomous agents.",
        "mimeType": "application/json",
    }


def seller_manifest() -> dict:
    """Return the public x402 service document without querying a provider."""

    return {
        # true402 consumes the seller manifest schema (x402 1.0).  The
        # payment challenge returned by /v1/public/ask remains x402 v2.
        "x402": "1.0",
        "name": "prama-dynamagh",
        "description": (
            "Evidence-bound intelligence acquisition for autonomous agents. "
            "Principle: paid_miner_output_is_not_authorization. "
            'Epistemic coverage: framework=E1/E2; e1_targets=["CRYPTO_PRICE"].'
        ),
        "capabilities": [
            "evidence_bound_intelligence_acquisition",
            "principle:paid_miner_output_is_not_authorization",
            "epistemic_coverage:framework=E1/E2;e1_targets=[CRYPTO_PRICE]",
        ],
        "pricing": {
            "currency": "USDC",
            "base": f"{X402_AMOUNT_USDC:.6f}",
            "unit": "request",
        },
        "payment": {
            "address": X402_RECIPIENT,
            # Keep the manifest truthful to the seller challenge.  This
            # deployment settles on Base Sepolia (eip155:84532).
            "chain": "base-sepolia" if X402_NETWORK == "eip155:84532" else X402_NETWORK,
            "facilitator": X402_FACILITATOR,
        },
        "endpoint": f"{PUBLIC_ORIGIN}/v1/public/ask",
    }


def _encoded(value: dict) -> str:
    return base64.b64encode(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()).decode()


def _challenge(resource: str | None = None, *, error: str | None = None) -> JSONResponse:
    required = {"x402Version": 2, "accepts": [_requirements(resource)]}
    body = {"x402Version": 2, "accepts": required["accepts"]}
    if error:
        body["error"] = error
    response = JSONResponse(body, status_code=status.HTTP_402_PAYMENT_REQUIRED)
    response.headers["PAYMENT-REQUIRED"] = _encoded(required)
    response.headers["Cache-Control"] = "no-store"
    return response


def _decode_payment(header: str) -> dict | None:
    try:
        padded = header + ("=" * (-len(header) % 4))
        raw = base64.urlsafe_b64decode(padded.encode())
        value = json.loads(raw.decode())
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _facilitator(operation: str, payload: dict, requirements: dict) -> dict:
    body = json.dumps(
        {"x402Version": 2, "paymentPayload": payload, "paymentRequirements": requirements},
        separators=(",", ":"),
    ).encode()
    request = UrlRequest(
        f"{X402_FACILITATOR}/{operation.lstrip('/')}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("X402_FACILITATOR_UNAVAILABLE") from error


def _payer(payment: dict) -> str | None:
    payload = payment.get("payload") if isinstance(payment.get("payload"), dict) else payment
    authorization = payload.get("authorization") if isinstance(payload.get("authorization"), dict) else payload
    value = authorization.get("from") or payload.get("from")
    return value if isinstance(value, str) and value.startswith("0x") else None


def _stable_context(payer: str, external_agent_id: str | None) -> str:
    material = f"x402:{payer.lower()}:{external_agent_id or ''}".encode()
    return "m2m-x402-sha256:" + hashlib.sha256(material).hexdigest()


RESULT_CAPABILITY_HEADER = "X-PRAMA-Result-Capability"


def _result_endpoint(mandate_id: str) -> str:
    return f"{PUBLIC_ORIGIN}/v1/public/ask/{mandate_id}/result"


def _new_result_capability() -> tuple[str, str]:
    """Issue a high-entropy, mandate-scoped secret and its persisted digest."""

    capability = secrets.token_urlsafe(32)
    digest = hashlib.sha256(capability.encode("utf-8")).hexdigest()
    return capability, digest


def _accepted_response(
    *, request_id: str, mandate_id: str, capability: str | None, replay: bool = False
) -> JSONResponse:
    endpoint = _result_endpoint(mandate_id)
    return JSONResponse(
        {
            "request_id": request_id,
            "mandate_id": mandate_id,
            "status": "RECEIVED",
            "result_endpoint": endpoint,
            "status_url": endpoint,
            "result_capability": capability,
            "result_capability_header": RESULT_CAPABILITY_HEADER,
            "result_capability_replay": replay,
        },
        status_code=status.HTTP_202_ACCEPTED,
        headers={"Cache-Control": "no-store"},
    )


def _x402_result_payload(session, mandate: Mandate, request_id: str) -> dict:
    """Build only the persisted read result for the authorized mandate."""

    tasks = (
        session.query(AcquisitionTask)
        .filter_by(mandate_id=mandate.mandate_id)
        .order_by(AcquisitionTask.ordinal)
        .all()
    )
    evidence_rows = (
        session.query(Evidence)
        .filter_by(mandate_id=mandate.mandate_id)
        .order_by(Evidence.created_at)
        .all()
    )
    evaluation = (
        session.query(StructuralEvaluation)
        .filter_by(mandate_id=mandate.mandate_id)
        .order_by(StructuralEvaluation.created_at.desc())
        .first()
    )
    decision = (
        session.query(Decision)
        .filter_by(mandate_id=mandate.mandate_id)
        .order_by(Decision.created_at.desc())
        .first()
    )
    ticket = (
        session.query(Ticket)
        .filter_by(mandate_id=mandate.mandate_id)
        .order_by(Ticket.created_at.desc())
        .first()
    )
    return {
        "request_id": request_id,
        "mandate_id": mandate.mandate_id,
        "origin": mandate.origin,
        "status": mandate.status,
        "text": mandate.text,
        "created_at": mandate.created_at,
        "updated_at": mandate.updated_at,
        "result_endpoint": _result_endpoint(mandate.mandate_id),
        "acquisitions": [
            {
                "acquisition_id": task.acquisition_id,
                "status": task.status,
                "requested_intent": task.requested_intent,
                "attempt_count": task.attempt_count,
                "failure_code": task.failure_code,
            }
            for task in tasks
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "content_hash": item.content_hash,
                "admissibility": item.admissibility,
                "provenance_status": item.provenance_status,
            }
            for item in evidence_rows
        ],
        "evaluation": None
        if evaluation is None
        else {
            "evaluation_id": evaluation.evaluation_id,
            "structural_state": evaluation.structural_state,
            "limitation_codes": evaluation.limitation_codes,
            "contradiction_codes": evaluation.contradiction_codes,
        },
        "decision": None
        if decision is None
        else {
            "decision_id": decision.decision_id,
            "state": decision.state,
            "policy_version": decision.policy_version,
            "reason_codes": decision.reason_codes,
        },
        "ticket": None
        if ticket is None
        else {
            "ticket_id": ticket.ticket_id,
            "ticket_hash": ticket.ticket_hash,
            "schema_version": ticket.schema_version,
            "hash_algorithm": ticket.hash_algorithm,
            "anchor_status": ticket.anchor_status,
        },
    }


def _request_fingerprint(intent: str | None, query: str) -> str:
    material = json.dumps({"intent": intent, "request": query}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(material).hexdigest()


def _stored_request_fingerprint(payment: InboundX402Payment) -> str | None:
    try:
        value = json.loads(payment.settlement_reference or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value.get("request_hash") if isinstance(value, dict) else None


def _create_verified_payment(
    session: Session,
    *,
    request_id: str,
    idempotency_key: str,
    payer: str,
    request_fingerprint: str,
)-> InboundX402Payment:
    """Persist the verified payment attempt before settlement, without work."""
    payment_row = InboundX402Payment(
        request_id=request_id,
        payer_wallet_address=payer,
        recipient_wallet_address=X402_RECIPIENT,
        network=X402_NETWORK,
        asset=X402_ASSET,
        amount_usdc=X402_AMOUNT_USDC,
        facilitator=X402_FACILITATOR,
        payment_status="VERIFIED",
        idempotency_key=idempotency_key,
        verified_at=datetime.now(timezone.utc),
        settlement_reference=json.dumps({"request_hash": request_fingerprint}, separators=(",", ":")),
    )
    session.add(payment_row)
    session.flush()
    return payment_row


def _create_settled_mandate(
    session: Session,
    *,
    request_id: str,
    query: str,
    intent: str | None,
    payer: str,
    external_agent_id: str | None,
    payment_row: InboundX402Payment,
    result_capability_hash: str,
) -> tuple[Mandate, AcquisitionTask]:
    """Create M2M work only after the inbound payment is settled."""
    context_id = _stable_context(payer, external_agent_id)
    identity = get_or_create_m2m_identity(session, external_agent_id, context_id) if external_agent_id else None
    mandate = Mandate(
        actor_id="x402-public",
        agent_id=external_agent_id,
        agent_identity_id=identity.agent_id if identity else None,
        m2m_context_id=context_id,
        client_id="x402-inbound",
        text=query,
        mandate_type="GENERAL",
        constraints={
            "request_id": request_id,
            "source_principal": "X402_PUBLIC",
            "external_agent_id": external_agent_id,
            "payer_wallet": payer,
            "intent": intent,
            "payment_rail": "X402",
        },
        max_budget_usdc=X402_AMOUNT_USDC,
        status=MandateStatus.RECEIVED.value,
        origin="M2M",
    )
    session.add(mandate)
    session.flush()
    payment_row.result_capability_hash = result_capability_hash
    reserve_m2m_spend(session, mandate.mandate_id, X402_AMOUNT_USDC)
    task = AcquisitionTask(
        mandate_id=mandate.mandate_id,
        query=query,
        requested_intent=intent,
        required=True,
        status="QUEUED",
        ordinal=0,
        resource_provider="TELEGRAPH",
        access_mechanism="GATEWAY",
        payment_rail="X402",
    )
    session.add(task)
    payment_row.mandate_id = mandate.mandate_id
    metadata = {
        "origin": "M2M",
        "source_principal": "X402_PUBLIC",
        "external_agent_id": external_agent_id,
        "payer_wallet": payer,
        "request_id": request_id,
        "payment_rail": "X402",
    }
    session.add_all(
        [
            MandateTransition(mandate_id=mandate.mandate_id, from_status=None, to_status=MandateStatus.RECEIVED.value, reason="x402 inbound payment verified"),
            UsageEvent(mandate_id=mandate.mandate_id, event_type="MANDATE_CREATED", metadata_=metadata),
            UsageEvent(mandate_id=mandate.mandate_id, acquisition_id=task.acquisition_id, event_type="ACQUISITION_QUEUED", metadata_=metadata),
        ]
    )
    session.flush()
    return mandate, task


@router.get("/.well-known/x402-service.json", include_in_schema=False)
def x402_service_manifest() -> dict:
    return seller_manifest()


@router.post("/v1/public/ask", include_in_schema=False)
async def public_x402_ask(request: Request):
    """Challenge or settle one inbound x402 request before M2M dispatch."""

    resource = f"{PUBLIC_ORIGIN}/v1/public/ask"
    payment_header = request.headers.get("payment-signature") or request.headers.get("x-payment")
    if not payment_header:
        return _challenge(resource)
    payment = _decode_payment(payment_header)
    if payment is None:
        return _challenge(resource, error="X402_PAYMENT_HEADER_INVALID")
    payer = _payer(payment)
    if payer is None:
        return _challenge(resource, error="X402_PAYER_MISSING")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"code": "X402_REQUEST_BODY_REQUIRED"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"code": "X402_REQUEST_INVALID"}, status_code=422)
    query = body.get("request") or body.get("query")
    intent = body.get("intent")
    if not isinstance(query, str) or not query.strip() or (intent is not None and not isinstance(intent, str)):
        return JSONResponse({"code": "X402_REQUEST_INVALID"}, status_code=422)
    requirements = _requirements(resource)
    idempotency_key = request.headers.get("idempotency-key") or ("x402:" + hashlib.sha256(payment_header.encode()).hexdigest())
    if len(idempotency_key) > 128:
        return JSONResponse({"code": "X402_IDEMPOTENCY_KEY_INVALID"}, status_code=400)
    # Wallet is the economic principal only. Agent identity is explicit via
    # X-Agent-Id; anonymous paid callers leave external_agent_id NULL.
    external_agent_id = request.headers.get("x-agent-id") or None
    request_fingerprint = _request_fingerprint(intent, query)
    session = SessionLocal()
    try:
        existing = session.query(InboundX402Payment).filter_by(idempotency_key=idempotency_key).one_or_none()
        if existing is not None and existing.payment_status == "SETTLED":
            if _stored_request_fingerprint(existing) != request_fingerprint:
                return JSONResponse({"code": "X402_IDEMPOTENCY_KEY_REUSED"}, status_code=409)
            return _accepted_response(
                request_id=existing.request_id,
                mandate_id=existing.mandate_id,
                capability=None,
                replay=True,
            )
        if existing is not None:
            return JSONResponse({"code": "X402_PAYMENT_IN_PROGRESS", "request_id": existing.request_id}, status_code=409)
        request_id = str(uuid.uuid4())
    except (IntegrityError, ValueError, InvalidOperation):
        session.rollback()
        return JSONResponse({"code": "X402_IDEMPOTENCY_UNAVAILABLE"}, status_code=503)
    except Exception:
        session.rollback()
        return JSONResponse({"code": "X402_MANDATE_UNAVAILABLE"}, status_code=503)
    finally:
        session.close()
    try:
        verified = _facilitator("verify", payment, requirements)
    except RuntimeError:
        return JSONResponse({"code": "X402_VERIFY_UNAVAILABLE"}, status_code=503)
    if verified.get("isValid") is not True:
        return _challenge(resource, error=str(verified.get("invalidReason") or "X402_VERIFY_FAILED"))
    session = SessionLocal()
    try:
        # The idempotency row is created only after verification, so a failed
        # verification cannot create work or reserve budget.
        payment_row = _create_verified_payment(
            session,
            request_id=request_id,
            idempotency_key=idempotency_key,
            payer=payer,
            request_fingerprint=request_fingerprint,
        )
        session.commit()
    except (IntegrityError, ValueError, InvalidOperation):
        session.rollback()
        return JSONResponse({"code": "X402_IDEMPOTENCY_UNAVAILABLE"}, status_code=503)
    except Exception:
        session.rollback()
        return JSONResponse({"code": "X402_PAYMENT_UNAVAILABLE"}, status_code=503)
    finally:
        session.close()
    try:
        settled = _facilitator("settle", payment, requirements)
    except RuntimeError:
        settled = {"success": False, "errorReason": "X402_SETTLE_UNAVAILABLE"}
    if settled.get("success") is not True:
        session = SessionLocal()
        try:
            row = session.get(InboundX402Payment, payment_row.payment_id)
            if row:
                row.payment_status = "FAILED_SETTLE"
            session.commit()
        finally:
            session.close()
        return JSONResponse({"code": "X402_SETTLE_FAILED", "detail": settled.get("errorReason")}, status_code=402)
    tx_hash = settled.get("transaction") or settled.get("txHash")
    result_capability, result_capability_hash = _new_result_capability()
    session = SessionLocal()
    try:
        row = session.get(InboundX402Payment, payment_row.payment_id)
        if row:
            row.payment_status = "SETTLED"
            row.tx_hash = tx_hash
            row.settlement_reference = json.dumps(
                {"request_hash": request_fingerprint, "settlement": settled},
                separators=(",", ":"),
            )[:255]
            row.settled_at = datetime.now(timezone.utc)
            mandate, task = _create_settled_mandate(
                session,
                request_id=request_id,
                query=query,
                intent=intent,
                payer=payer,
                external_agent_id=external_agent_id,
                payment_row=row,
                result_capability_hash=result_capability_hash,
            )
        session.commit()
    except Exception:
        session.rollback()
        return JSONResponse({"code": "X402_MANDATE_UNAVAILABLE"}, status_code=503)
    finally:
        session.close()
    try:
        execute_acquisition.delay(mandate.mandate_id, task.acquisition_id)
    except Exception:
        pass
    return _accepted_response(
        request_id=request_id,
        mandate_id=mandate.mandate_id,
        capability=result_capability,
    )


@router.get("/v1/public/ask/{mandate_id}/result", include_in_schema=False)
def get_x402_result(mandate_id: str, request: Request):
    """Read one inbound x402 mandate using only its result capability.

    Invalid, missing, and cross-mandate capabilities all produce the same
    not-found response.  The capability is accepted only in a header and is
    never placed in a URL or logged.
    """

    supplied = request.headers.get(RESULT_CAPABILITY_HEADER.lower(), "")
    session = SessionLocal()
    try:
        payment = (
            session.query(InboundX402Payment)
            .filter_by(mandate_id=mandate_id, payment_status="SETTLED")
            .one_or_none()
        )
        if (
            payment is None
            or not payment.result_capability_hash
            or not supplied
            or not hmac.compare_digest(
                payment.result_capability_hash,
                hashlib.sha256(supplied.encode("utf-8")).hexdigest(),
            )
        ):
            return JSONResponse({"code": "X402_RESULT_NOT_FOUND"}, status_code=404)
        mandate = session.get(Mandate, mandate_id)
        if mandate is None or mandate.origin != "M2M":
            return JSONResponse({"code": "X402_RESULT_NOT_FOUND"}, status_code=404)
        return JSONResponse(
            jsonable_encoder(_x402_result_payload(session, mandate, payment.request_id)),
            headers={"Cache-Control": "no-store"},
        )
    finally:
        session.close()
