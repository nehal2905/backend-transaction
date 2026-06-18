"""Orchestrates the full pipeline (a -> e) and owns Job status transitions.

Called by the Celery task. Any unhandled exception marks the job failed; LLM
sub-failures are handled inside the steps and do NOT fail the job.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.enums import JobStatus
from app.models import Job, Transaction
from app.pipeline import anomaly, classify, summary
from app.pipeline.cleaning import clean_csv
from app.storage import read_upload

logger = logging.getLogger(__name__)


def run_pipeline(db: Session, job_id: uuid.UUID) -> None:
    job = db.get(Job, job_id)
    if job is None:
        logger.error("Job %s not found", job_id)
        return

    job.status = JobStatus.PROCESSING.value
    db.commit()

    try:
        # (a) cleaning
        content = read_upload(job.file_path)
        cleaning_result = clean_csv(content)
        job.row_count_raw = cleaning_result.row_count_raw
        job.row_count_clean = cleaning_result.row_count_clean

        transactions = [
            Transaction(
                job_id=job.id,
                txn_id=r.txn_id,
                date=r.date,
                merchant=r.merchant,
                amount=r.amount,
                currency=r.currency,
                status=r.status,
                category=r.category,
                account_id=r.account_id,
            )
            for r in cleaning_result.rows
        ]
        db.add_all(transactions)
        db.flush()

        # (b) anomaly detection
        anomaly_count = anomaly.detect_anomalies(transactions)

        # (c) LLM classification (batched; failures degrade gracefully)
        classify.classify_transactions(transactions)

        # (d) LLM narrative summary (single call; fallback on failure)
        job_summary = summary.build_summary(job.id, transactions, anomaly_count)
        db.add(job_summary)

        # (e) finalize
        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = None
        db.commit()
        logger.info("Job %s completed: %s txns", job_id, len(transactions))

    except Exception as exc:  # noqa: BLE001 - any unhandled error fails the job
        db.rollback()
        logger.exception("Job %s failed", job_id)
        job = db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED.value
            job.error_message = str(exc)[:2000]
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
