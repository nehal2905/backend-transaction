import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.enums import JobStatus
from app.models import Job, Transaction
from app.pipeline.cleaning import CSVValidationError, clean_csv, validate_header
from app.schemas import (
    AnomalyOut,
    JobListItem,
    ResultsResponse,
    StatusResponse,
    SummaryFull,
    SummaryStats,
    TransactionOut,
    UploadResponse,
)
from app.storage import save_upload
from app.tasks import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    # Validate extension / content type.
    filename = file.filename or "upload.csv"
    is_csv = filename.lower().endswith(".csv") or (
        file.content_type in {"text/csv", "application/vnd.ms-excel", "application/csv"}
    )
    if not is_csv:
        raise HTTPException(status_code=422, detail="File must be a .csv")

    raw = await file.read()
    if not raw or not raw.strip():
        raise HTTPException(status_code=422, detail="Uploaded CSV is empty")

    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"CSV not valid UTF-8: {exc}")

    # Validate header columns + count raw rows up front.
    try:
        validate_header(content)
        cleaning = clean_csv(content)
    except CSVValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if cleaning.row_count_raw == 0:
        raise HTTPException(status_code=422, detail="CSV has no data rows")

    job_id = uuid.uuid4()
    path = save_upload(job_id, raw)

    job = Job(
        id=job_id,
        filename=filename,
        file_path=path,
        status=JobStatus.PENDING.value,
        row_count_raw=cleaning.row_count_raw,
    )
    db.add(job)
    db.commit()

    process_job.delay(str(job_id))

    return UploadResponse(job_id=job_id, status=JobStatus.PENDING)


@router.get("/{job_id}/status", response_model=StatusResponse)
def job_status(job_id: uuid.UUID, db: Session = Depends(get_db)) -> StatusResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    summary_stats = None
    if job.status == JobStatus.COMPLETED.value and job.summary is not None:
        s = job.summary
        summary_stats = SummaryStats(
            total_spend_inr=s.total_spend_inr,
            total_spend_usd=s.total_spend_usd,
            anomaly_count=s.anomaly_count,
            risk_level=s.risk_level,
        )

    return StatusResponse(
        job_id=job.id,
        status=JobStatus(job.status),
        created_at=job.created_at,
        completed_at=job.completed_at,
        summary=summary_stats,
    )


@router.get("/{job_id}/results", response_model=ResultsResponse)
def job_results(job_id: uuid.UUID, db: Session = Depends(get_db)) -> ResultsResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Job not completed (status={job.status}); poll the status endpoint",
        )

    txns = (
        db.execute(
            select(Transaction).where(Transaction.job_id == job.id)
        )
        .scalars()
        .all()
    )

    cleaned = [TransactionOut.model_validate(t) for t in txns]
    anomalies = [
        AnomalyOut(
            txn_id=t.txn_id,
            merchant=t.merchant,
            amount=t.amount,
            anomaly_reason=t.anomaly_reason,
        )
        for t in txns
        if t.is_anomaly
    ]

    # category_breakdown: per-category spend using the final category.
    breakdown: dict[str, float] = defaultdict(float)
    for t in txns:
        breakdown[t.final_category] += float(t.amount)
    # Round to 2 dp to avoid float accumulation artifacts in the response.
    breakdown = {k: round(v, 2) for k, v in breakdown.items()}

    summary_full = None
    if job.summary is not None:
        s = job.summary
        summary_full = SummaryFull(
            total_spend_inr=s.total_spend_inr,
            total_spend_usd=s.total_spend_usd,
            top_merchants=s.top_merchants,
            anomaly_count=s.anomaly_count,
            narrative=s.narrative,
            risk_level=s.risk_level,
        )

    return ResultsResponse(
        job_id=job.id,
        cleaned_transactions=cleaned,
        anomalies=anomalies,
        category_breakdown=dict(breakdown),
        summary=summary_full,
    )


@router.get("", response_model=list[JobListItem])
def list_jobs(
    status: JobStatus | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[JobListItem]:
    stmt = select(Job)
    if status is not None:
        stmt = stmt.where(Job.status == status.value)
    stmt = stmt.order_by(Job.created_at.desc())

    jobs = db.execute(stmt).scalars().all()
    return [
        JobListItem(
            job_id=j.id,
            filename=j.filename,
            status=JobStatus(j.status),
            row_count_raw=j.row_count_raw,
            created_at=j.created_at,
        )
        for j in jobs
    ]
