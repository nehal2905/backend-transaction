"""Step (b): anomaly detection over persisted Transaction objects.

Two independent rules, each may add a reason; reasons are joined with "; ".
Operates by mutating the passed Transaction objects (is_anomaly / anomaly_reason).
"""

import statistics
from collections import defaultdict
from decimal import Decimal

from app.config import settings
from app.enums import Currency
from app.models import Transaction

AMOUNT_REASON = "amount > 3x account median"
CURRENCY_REASON = "USD on domestic-only merchant"


def _domestic_set() -> set[str]:
    return {m.strip().lower() for m in settings.domestic_only_merchants}


def detect_anomalies(transactions: list[Transaction]) -> int:
    """Flag anomalies in-place. Returns the count of anomalous transactions."""
    domestic = _domestic_set()
    multiplier = Decimal(str(settings.anomaly_amount_multiplier))

    # Median amount per (account_id, currency) so we never mix INR vs USD scale.
    groups: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    for txn in transactions:
        groups[(txn.account_id, txn.currency)].append(txn.amount)

    medians: dict[tuple[str, str], Decimal] = {}
    for key, amounts in groups.items():
        medians[key] = Decimal(str(statistics.median(amounts)))

    anomaly_count = 0
    for txn in transactions:
        reasons: list[str] = []

        median = medians.get((txn.account_id, txn.currency))
        if median is not None and median > 0 and txn.amount > multiplier * median:
            reasons.append(AMOUNT_REASON)

        if (
            txn.currency == Currency.USD.value
            and txn.merchant.strip().lower() in domestic
        ):
            reasons.append(CURRENCY_REASON)

        if reasons:
            txn.is_anomaly = True
            txn.anomaly_reason = "; ".join(reasons)
            anomaly_count += 1
        else:
            txn.is_anomaly = False
            txn.anomaly_reason = None

    return anomaly_count
