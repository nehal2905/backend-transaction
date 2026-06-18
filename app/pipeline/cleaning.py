"""Step (a): parse + normalize raw CSV rows.

Pure functions, no DB / Celery dependency, so this is unit-testable on its own.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Header columns we require in the uploaded CSV (case-insensitive).
EXPECTED_COLUMNS = {
    "txn_id",
    "date",
    "merchant",
    "amount",
    "currency",
    "status",
    "category",
    "account_id",
}

# Explicit date formats, tried in order. DD-MM-YYYY before MM-DD so that
# 03-04-2024 is unambiguously read as day-month (4 April 2024).
_DATE_FORMATS = [
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%d/%m/%Y",
]


@dataclass(frozen=True)
class CleanedRow:
    txn_id: str | None
    date: date | None
    merchant: str
    amount: Decimal
    currency: str
    status: str
    category: str
    account_id: str

    def dedup_key(self) -> tuple:
        return (
            self.txn_id,
            self.date,
            self.merchant,
            self.amount,
            self.currency,
            self.status,
            self.category,
            self.account_id,
        )


@dataclass
class CleaningResult:
    rows: list[CleanedRow]
    row_count_raw: int
    row_count_clean: int
    skipped: list[str] = field(default_factory=list)


class CSVValidationError(Exception):
    """Raised when the CSV is structurally invalid (used for 422)."""


def validate_header(content: str) -> list[str]:
    """Validate that the header contains the expected columns. Returns fieldnames."""
    reader = csv.reader(io.StringIO(content))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise CSVValidationError("CSV is empty") from exc

    normalized = {h.strip().lower() for h in header}
    missing = EXPECTED_COLUMNS - normalized
    if missing:
        raise CSVValidationError(
            f"CSV missing required columns: {', '.join(sorted(missing))}"
        )
    return header


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Decimal:
    raw = (raw or "").strip()
    # Strip currency symbol, whitespace, and thousands separators.
    raw = raw.lstrip("$").replace(",", "").strip()
    if not raw:
        return Decimal("0")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("0")


def _norm(value: str | None) -> str:
    return (value or "").strip()


def clean_csv(content: str) -> CleaningResult:
    """Parse + normalize CSV content into deduped CleanedRow objects."""
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise CSVValidationError("CSV is empty")

    # Map normalized header -> actual key so we read regardless of case/spacing.
    keymap = {h.strip().lower(): h for h in reader.fieldnames if h is not None}
    missing = EXPECTED_COLUMNS - set(keymap)
    if missing:
        raise CSVValidationError(
            f"CSV missing required columns: {', '.join(sorted(missing))}"
        )

    def get(row: dict, col: str) -> str:
        return _norm(row.get(keymap[col]))

    raw_count = 0
    seen: set[tuple] = set()
    rows: list[CleanedRow] = []

    for row in reader:
        # Skip wholly empty lines.
        if not any((v or "").strip() for v in row.values()):
            continue
        raw_count += 1

        category = get(row, "category") or "Uncategorised"
        cleaned = CleanedRow(
            txn_id=get(row, "txn_id") or None,
            date=_parse_date(get(row, "date")),
            merchant=get(row, "merchant"),
            amount=_parse_amount(get(row, "amount")),
            currency=get(row, "currency").upper(),
            status=get(row, "status").upper(),
            category=category,
            account_id=get(row, "account_id"),
        )

        key = cleaned.dedup_key()
        if key in seen:
            continue
        seen.add(key)
        rows.append(cleaned)

    return CleaningResult(
        rows=rows,
        row_count_raw=raw_count,
        row_count_clean=len(rows),
    )
