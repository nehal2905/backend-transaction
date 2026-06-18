"""Step (c): LLM classification of originally-blank-category transactions.

Batched (settings.llm_batch_size per call), never one call per row. A batch that
exhausts retries marks its transactions llm_failed=true and is skipped — the job
keeps going.
"""

import json
import logging

from app.config import settings
from app.enums import LLM_CATEGORIES
from app.llm.client import LLMError, call_gemini_json
from app.llm.prompts import build_classify_prompt
from app.models import Transaction

logger = logging.getLogger(__name__)

_VALID = set(LLM_CATEGORIES)


def _needs_classification(txn: Transaction) -> bool:
    # Original category was blank → stored as 'Uncategorised' in cleaning.
    return txn.category == "Uncategorised"


def classify_transactions(transactions: list[Transaction]) -> None:
    targets = [t for t in transactions if _needs_classification(t)]
    if not targets:
        return

    batch_size = max(1, settings.llm_batch_size)
    for start in range(0, len(targets), batch_size):
        batch = targets[start : start + batch_size]
        _classify_batch(batch)


def _classify_batch(batch: list[Transaction]) -> None:
    items = [
        {
            "index": i,
            "merchant": t.merchant,
            "amount": str(t.amount),
            "currency": t.currency,
        }
        for i, t in enumerate(batch)
    ]
    prompt = build_classify_prompt(items)

    try:
        result = call_gemini_json(prompt)
    except LLMError as exc:
        logger.warning("Classification batch failed after retries: %s", exc)
        for t in batch:
            t.llm_failed = True
            t.llm_raw_response = f"ERROR: {exc}"
        return

    raw = json.dumps(result)
    for i, txn in enumerate(batch):
        txn.llm_raw_response = raw
        category = result.get(str(i)) or result.get(i)
        if isinstance(category, str) and category in _VALID:
            txn.llm_category = category
            txn.llm_failed = False
        else:
            # Model omitted or returned an out-of-vocabulary label for this row.
            txn.llm_category = None
            txn.llm_failed = True
