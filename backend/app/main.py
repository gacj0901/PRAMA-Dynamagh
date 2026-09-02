from fastapi import FastAPI

from app.api.mandates import router as mandates_router

app = FastAPI(title="PRAMA-Dynamagh API", version="0.0.1")
app.include_router(mandates_router)

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
