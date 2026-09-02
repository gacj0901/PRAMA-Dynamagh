from fastapi import FastAPI, HTTPException, status

from app.api.mandates import router as mandates_router

app = FastAPI(title="PRAMA-Dynamagh API", version="0.0.1")
app.include_router(mandates_router)


@app.post("/v1/tickets/{ticket_id}/anchor", status_code=status.HTTP_202_ACCEPTED)
def request_ticket_anchor(ticket_id: str):
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
def health() -> dict[str, str]:
    return {"status": "ok", "service": "prama-dynamagh-api"}
