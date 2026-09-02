from fastapi import FastAPI

from app.api.mandates import router as mandates_router

app = FastAPI(title="PRAMA-Dynamagh API", version="0.0.1")
app.include_router(mandates_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "prama-dynamagh-api"}
