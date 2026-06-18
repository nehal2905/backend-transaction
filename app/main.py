from fastapi import FastAPI

from app.api import jobs
from app.storage import ensure_upload_dir

app = FastAPI(
    title="AI-Powered Transaction Processing Pipeline",
    description=(
        "Upload a transactions CSV, then poll for an async pipeline that cleans, "
        "detects anomalies, classifies via LLM, and produces an AI summary."
    ),
    version="1.0.0",
)

app.include_router(jobs.router)


@app.on_event("startup")
def _startup() -> None:
    ensure_upload_dir()


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}
