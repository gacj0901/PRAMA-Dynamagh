from fastapi import FastAPI, HTTPException, status

from app.api.mandates import router as mandates_router
from app.api.autonomy import router as autonomy_router
from app.api.m2m import router as m2m_router
from app.api.agents import router as agents_router
from app.api.observer import router as observer_router
from app.api.public_surfaces import router as public_surfaces_router

app = FastAPI(title="PRAMA-Dynamagh API", version="0.0.1")
app.include_router(mandates_router)
app.include_router(autonomy_router)
app.include_router(m2m_router)
app.include_router(agents_router)
app.include_router(observer_router)
app.include_router(public_surfaces_router)


@app.post("/v1/erc8183/jobs", status_code=status.HTTP_404_NOT_FOUND, include_in_schema=False)
def request_erc8183_job():
    # Public production deliberately has no ERC-8183 write surface.
    raise HTTPException(status_code=404, detail="NOT_FOUND")
    from app.erc8183.service import request_fixture
    from app.persistence.database import SessionLocal
    from app.workers.tasks import execute_erc8183_job
    session = SessionLocal()
    try:
        job, result = request_fixture(session)
        session.commit()
        if result == "PREPARING": execute_erc8183_job.delay(job.erc8183_job_id)
        return {"erc8183_job_id": job.erc8183_job_id, "status": result}
    finally: session.close()


@app.get("/v1/erc8183/jobs")
def list_erc8183_jobs():
    """Read-only ERC-8183 inventory for the PRAMA operator interface."""
    from app.domain.mandates import ERC8183Job
    from app.persistence.database import SessionLocal
    session = SessionLocal()
    try:
        jobs = session.query(ERC8183Job).order_by(ERC8183Job.updated_at.desc()).all()
        return [_erc8183_response(job) for job in jobs]
    finally:
        session.close()


@app.get("/v1/erc8183/jobs/{erc8183_job_id}")
def get_erc8183_job(erc8183_job_id: str):
    from app.domain.mandates import ERC8183Job
    from app.persistence.database import SessionLocal
    session = SessionLocal()
    try:
        job = session.get(ERC8183Job, erc8183_job_id)
        if not job: raise HTTPException(status_code=404, detail="ERC8183_JOB_MISSING")
        return _erc8183_response(job)
    finally: session.close()


@app.get("/v1/erc8183/jobs/{erc8183_job_id}/chain")
def get_erc8183_chain(erc8183_job_id: str):
    from app.domain.mandates import ERC8183Job
    from app.persistence.database import SessionLocal
    from urllib.request import urlopen
    import json, os
    session = SessionLocal()
    try:
        job = session.get(ERC8183Job, erc8183_job_id)
        if not job or not job.telegraph_job_id: raise HTTPException(status_code=404, detail="ERC8183_JOB_NOT_SUBMITTED")
        with urlopen(os.environ["GATEWAY_URL"] + f"/chain/erc8183/jobs/{job.telegraph_job_id}", timeout=20) as response: return json.loads(response.read())
    finally: session.close()


@app.get("/v1/erc8183/jobs/{erc8183_job_id}/lineage")
def get_erc8183_lineage(erc8183_job_id: str):
    """Read-only G9 lineage surface; promotion remains deliberately disabled."""
    from app.erc8183.evidence import lineage
    from app.persistence.database import SessionLocal
    session = SessionLocal()
    try:
        try:
            return lineage(session, erc8183_job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    finally:
        session.close()


@app.post("/v1/erc8183/jobs/{erc8183_job_id}/cancel", status_code=status.HTTP_404_NOT_FOUND, include_in_schema=False)
def cancel_erc8183_job(erc8183_job_id: str):
    # Cancellation is an on-chain action and is never available publicly.
    raise HTTPException(status_code=404, detail="NOT_FOUND")
    from app.domain.mandates import ERC8183Job
    from app.persistence.database import SessionLocal
    from app.workers.tasks import cancel_erc8183_job as task, cancellation_allowed
    session = SessionLocal()
    try:
        job = session.get(ERC8183Job, erc8183_job_id)
        if not job: raise HTTPException(status_code=404, detail="ERC8183_JOB_MISSING")
        if not cancellation_allowed(job): raise HTTPException(status_code=409, detail="ERC8183_CANCEL_INVALID")
        job.chain_state = "FUNDED"; job.state = "CANCEL_PENDING"; session.commit(); task.delay(erc8183_job_id)
        return {"erc8183_job_id": erc8183_job_id, "status": "CANCEL_PENDING"}
    finally: session.close()


def _erc8183_response(job):
    return {key: getattr(job, key) for key in ("erc8183_job_id", "mandate_id", "ticket_id", "chain_id", "diamond_address", "telegraph_job_id", "intent_name", "intent_id", "callback_address", "callback_response_hash", "callback_verified", "callback_verified_at", "params_payload", "state", "chain_state", "budget_usdc", "miner_payment_usdc", "protocol_fee_usdc", "output_hash", "approval_tx_hash", "approval_block_number", "deposit_tx_hash", "deposit_block_number", "create_tx_hash", "create_block_number", "terminal_tx_hash", "terminal_block_number", "cancel_tx_hash", "cancel_block_number", "failure_code", "created_at", "updated_at", "terminal_at", "cancelled_at")}


@app.post("/v1/tickets/{ticket_id}/anchor", status_code=status.HTTP_404_NOT_FOUND, include_in_schema=False)
def request_ticket_anchor(ticket_id: str):
    # Tickets stay read-only from the public deployment surface.
    raise HTTPException(status_code=404, detail="NOT_FOUND")
    from app.anchors.service import request_anchor
    from app.persistence.database import SessionLocal
    from app.workers.tasks import execute_ticket_anchor
    session = SessionLocal()
    try:
        try:
            attempt, result = request_anchor(session, ticket_id)
        except ValueError as error:
            raise HTTPException(status_code=409 if str(error) != "TICKET_MISSING" else 404, detail=str(error)) from error
        session.commit()
        if result in {"ANCHOR_PENDING", "ALREADY_ANCHOR_PENDING"}:
            execute_ticket_anchor.delay(ticket_id)
        return {"ticket_id": ticket_id, "anchor_attempt_id": attempt.anchor_attempt_id, "status": result}
    finally:
        session.close()


@app.get("/v1/tickets/{ticket_id}/anchor")
def get_ticket_anchor(ticket_id: str):
    from app.domain.mandates import AnchorAttempt, Ticket
    from app.persistence.database import SessionLocal
    session = SessionLocal()
    try:
        ticket = session.get(Ticket, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="TICKET_MISSING")
        attempt = session.query(AnchorAttempt).filter_by(ticket_id=ticket_id).one_or_none()
        return {
            "ticket_id": ticket_id,
            "anchor_status": ticket.anchor_status,
            "anchor_attempt": None if not attempt else {
                "anchor_attempt_id": attempt.anchor_attempt_id,
                "status": attempt.status,
                "chain_id": attempt.chain_id,
                "contract_address": attempt.contract_address,
                "tx_hash": attempt.tx_hash,
                "block_number": attempt.block_number,
                "block_hash": attempt.block_hash,
                "failure_code": attempt.failure_code,
            },
        }
    finally:
        session.close()

@app.get("/v1/tickets/{ticket_id}/verify")
def verify_ticket(ticket_id: str):
    from app.persistence.database import SessionLocal
    from app.domain.mandates import Ticket
    from app.tickets.service import verify
    s=SessionLocal()
    try:
        t=s.get(Ticket,ticket_id)
        if not t: return {"status":"INVALID","failure_codes":["TICKET_MISSING"]}
        return {"ticket_id":ticket_id,**verify(s,t)}
    finally:s.close()


@app.get("/health")
def health() -> dict:
    from app.public_safety import public_daily_spend_cap_usdc, public_max_mandate_usdc, public_rate_limit, m2m_max_workflow_usdc, MAX_SINGLE_ACQUISITION_USDC
    from app.competition import competition_max_calls_per_workflow
    from app.redis_config import redis_runtime_diagnostics
    rate_limit, rate_window = public_rate_limit()
    return {
        "status": "ok",
        "service": "prama-dynamagh-api",
        "public_execution": {
            "max_mandate_usdc": f"{public_max_mandate_usdc():.6f}",
            "daily_spend_cap_usdc": f"{public_daily_spend_cap_usdc():.6f}",
            "rate_limit": rate_limit,
            "rate_window_seconds": rate_window,
            "max_single_acquisition_usdc": f"{MAX_SINGLE_ACQUISITION_USDC:.6f}",
            "m2m_max_workflow_usdc": f"{m2m_max_workflow_usdc():.6f}",
            "fanout_max_tasks_per_mandate": competition_max_calls_per_workflow(),
            "typed_epistemic_contracts": ["CRYPTO_PRICE"],
            "typed_epistemic_runtime": "ONLY_WHERE_PERSISTED_E1_EXISTS",
            "authority_mode": "SHADOW_ONLY",
        },
        "redis_runtime": redis_runtime_diagnostics(),
    }
