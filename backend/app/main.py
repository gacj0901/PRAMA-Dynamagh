from fastapi import FastAPI

app = FastAPI(title="PRAMA-Dynamagh API", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "prama-dynamagh-api"}

