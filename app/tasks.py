import uuid

from app.celery_app import celery
from app.database import SessionLocal
from app.pipeline.runner import run_pipeline


@celery.task(name="app.tasks.process_job")
def process_job(job_id: str) -> str:
    """Celery entrypoint: run the full pipeline for a single job."""
    db = SessionLocal()
    try:
        run_pipeline(db, uuid.UUID(str(job_id)))
    finally:
        db.close()
    return str(job_id)
