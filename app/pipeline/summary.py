"""Step (d): single-call LLM narrative summary, persisted as JobSummary.

We compute the numeric aggregates locally (ground truth) and ask the LLM only to
add a narrative + risk_level. If the LLM call exhausts retries we fall back to a
deterministic summary so /results still returns cleanly.
"""

import logging
import uuid
from collections import defaultdict
from decimal import Decimal

from app.enums import Currency, RiskLevel
from app.llm.client import LLMError, call_gemini_json
from app.llm.prompts import build_summary_prompt
from app.models import JobSummary, Transaction

logger = logging.getLogger(__name__)

FALLBACK_NARRATIVE = "LLM summary unavailable"


def compute_aggregates(transactions: list[Transaction], anomaly_count: int) -> dict:
    total_inr = Decimal("0")
    total_usd = Decimal("0")
    merchant_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    merchant_counts: dict[str, int] = defaultdict(int)

    for t in transactions:
        if t.currency == Currency.INR.value:
            total_inr += t.amount
        elif t.currency == Currency.USD.value:
            total_usd += t.amount
        merchant_totals[t.merchant] += t.amount
        merchant_counts[t.merchant] += 1

    top = sorted(merchant_totals.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_merchants = [
        {
            "merchant": m,
            "total": float(total),
            "count": merchant_counts[m],
        }
        for m, total in top
    ]

    return {
        "total_spend_inr": float(total_inr),
        "total_spend_usd": float(total_usd),
        "top_merchants": top_merchants,
        "anomaly_count": anomaly_count,
        "transaction_count": len(transactions),
    }


def _deterministic_risk(anomaly_count: int, total_txns: int) -> RiskLevel:
    if total_txns == 0:
        return RiskLevel.LOW
    ratio = anomaly_count / total_txns
    if anomaly_count >= 10 or ratio >= 0.2:
        return RiskLevel.HIGH
    if anomaly_count >= 3 or ratio >= 0.05:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def build_summary(
    job_id: uuid.UUID,
    transactions: list[Transaction],
    anomaly_count: int,
) -> JobSummary:
    agg = compute_aggregates(transactions, anomaly_count)
    fallback_risk = _deterministic_risk(anomaly_count, len(transactions))

    narrative = FALLBACK_NARRATIVE
    risk_level = fallback_risk.value

    try:
        result = call_gemini_json(build_summary_prompt(agg))
        narrative = str(result.get("narrative") or FALLBACK_NARRATIVE)
        risk_candidate = str(result.get("risk_level", "")).lower()
        if risk_candidate in {r.value for r in RiskLevel}:
            risk_level = risk_candidate
    except LLMError as exc:
        logger.warning("Summary LLM call failed after retries: %s", exc)

    return JobSummary(
        job_id=job_id,
        total_spend_inr=Decimal(str(agg["total_spend_inr"])),
        total_spend_usd=Decimal(str(agg["total_spend_usd"])),
        top_merchants=agg["top_merchants"],
        anomaly_count=anomaly_count,
        narrative=narrative,
        risk_level=risk_level,
    )
