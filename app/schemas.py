import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.enums import Currency, JobStatus, RiskLevel, TxnStatus


# ---------- Upload ----------
class UploadResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus


# ---------- Summary (nested) ----------
class TopMerchant(BaseModel):
    merchant: str
    total: float
    count: int


class SummaryStats(BaseModel):
    """High-level stats embedded in the status endpoint."""

    total_spend_inr: Decimal
    total_spend_usd: Decimal
    anomaly_count: int
    risk_level: RiskLevel


class SummaryFull(BaseModel):
    total_spend_inr: Decimal
    total_spend_usd: Decimal
    top_merchants: list[TopMerchant]
    anomaly_count: int
    narrative: str
    risk_level: RiskLevel


# ---------- Status ----------
class StatusResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    created_at: datetime
    completed_at: datetime | None = None
    summary: SummaryStats | None = None


# ---------- Results ----------
class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    txn_id: str | None
    date: date | None
    merchant: str
    amount: Decimal
    currency: Currency
    status: TxnStatus
    category: str
    account_id: str
    is_anomaly: bool
    anomaly_reason: str | None
    llm_category: str | None
    llm_failed: bool
    final_category: str


class AnomalyOut(BaseModel):
    txn_id: str | None
    merchant: str
    amount: Decimal
    anomaly_reason: str | None


class ResultsResponse(BaseModel):
    job_id: uuid.UUID
    cleaned_transactions: list[TransactionOut]
    anomalies: list[AnomalyOut]
    category_breakdown: dict[str, float]
    summary: SummaryFull | None = None


# ---------- List ----------
class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    filename: str
    status: JobStatus
    row_count_raw: int
    created_at: datetime
