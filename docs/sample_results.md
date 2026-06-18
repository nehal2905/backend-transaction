# Sample Processing Results

A reference run of the pipeline against the bundled dataset
(`data/transactions.csv`), demonstrating each stage end-to-end: cleaning →
anomaly detection → LLM classification → AI summary.

| | |
|---|---|
| **Input file** | `data/transactions.csv` |
| **Pipeline** | `cleaning → anomaly → classify → summary` (`app/pipeline/runner.py`) |
| **Final job status** | `completed` |

> **Reproducibility note.** The deterministic stages (cleaning, dedup, anomaly
> detection, aggregation) are computed directly from the current code logic and are
> exact. The LLM-dependent fields (per-row `llm_category`, `narrative`) are shown as
> representative output; with a `GEMINI_API_KEY` configured these are produced by
> Gemini 1.5 Flash at runtime, while all numeric results remain identical.

---

## 1. Ingestion & cleaning

| Metric | Value |
|---|---:|
| Raw rows | **95** |
| Duplicate rows removed | **10** |
| Clean rows | **85** |
| Rows missing `txn_id` | **4** |
| Rows missing `category` | **15** raw → **13** after dedup |

Normalizations applied per row:

- **Dates** parsed as `DD-MM-YYYY` and emitted as ISO `YYYY-MM-DD`.
- **Amounts** stripped of `$`/whitespace and cast to `Decimal` (e.g. `$11325.79 → 11325.79`).
- **`status` / `currency`** upper-cased (e.g. `success → SUCCESS`, `inr → INR`).
- **Blank `category`** set to `Uncategorised` (these rows feed LLM classification).
- **Exact duplicates** dropped (compared on the 8 core fields).

> The dataset also contains a non-schema `notes` column; it passes validation and is
> ignored by processing. All 10 duplicates also matched on `notes`, so each is a
> genuine exact duplicate.

---

## 2. Anomaly detection

**Total anomalies: 10** — produced by two independent rules. The statistical median
is computed **per `(account_id, currency)`** so INR and USD magnitudes never mix.

| Rule | Reason string | Count |
|---|---|---:|
| Statistical outlier (`amount > 3 × account median`) | `amount > 3x account median` | 5 |
| Currency mismatch (USD on a domestic-only merchant) | `USD on domestic-only merchant` | 5 |

### Example anomalies — statistical outliers

| txn_id | merchant | account | amount | account median | 3× threshold |
|---|---|---|---:|---:|---:|
| TXN2003 | IRCTC | ACC002 | 193,647.29 | 9,547.87 | 28,643.61 |
| TXN2004 | IRCTC | ACC003 | 191,918.37 | 9,967.64 | 29,902.92 |
| TXN2000 | Jio Recharge | ACC002 | 175,917.65 | 9,547.87 | 28,643.61 |
| TXN2001 | Flipkart | ACC005 | 146,100.68 | 8,962.10 | 26,886.30 |
| TXN2002 | Ola | ACC001 | 91,185.10 | 6,562.24 | 19,686.71 |

### Example anomalies — currency mismatch

| txn_id | merchant | account | currency | amount |
|---|---|---|---|---:|
| TXN1075 | Zomato | ACC002 | USD | 14,430.57 |
| TXN1072 | Zomato | ACC005 | USD | 13,862.47 |
| *(blank)* | Zomato | ACC004 | USD | 7,605.06 |
| TXN1063 | Zomato | ACC005 | USD | 4,627.78 |
| TXN1021 | Zomato | ACC001 | USD | 2,536.35 |

> "Jio Recharge" is intentionally **not** flagged for currency mismatch: the
> domestic-only set matches the exact merchant name "Jio", not "Jio Recharge".

---

## 3. LLM classification

13 rows had a blank original category and were sent to the LLM in a single batch
(batch size 25), each labeled with one of the 8 fixed categories.

### Example classifications

| txn_id | merchant | assigned category |
|---|---|---|
| TXN1077 | HDFC ATM | Cash Withdrawal |
| TXN1013 | Swiggy | Food |
| TXN1051 | Ola | Transport |
| TXN2001 | Flipkart | Shopping |
| TXN2003 | IRCTC | Travel |
| TXN2000 | Jio Recharge | Utilities |
| TXN1000 | Amazon | Shopping |

*(6 further rows classified: `TXN1020`→Travel, `TXN2002`→Transport, `TXN2004`→Travel, `TXN1056`→Shopping, and two blank-`txn_id` Jio Recharge rows→Utilities.)*

---

## 4. Final summary

| Field | Value |
|---|---|
| Total INR spend | **₹1,339,923.00** |
| Total USD spend | **$74,185.14** |
| Anomaly count | **10** |
| Risk level | **high** |

**Top 3 merchants** (by total spend):

| Rank | Merchant | Total | Transactions |
|---|---|---:|---:|
| 1 | IRCTC | 450,697.69 | 12 |
| 2 | Jio Recharge | 270,255.97 | 12 |
| 3 | Flipkart | 227,539.88 | 12 |

**Risk level:** `high` — assigned when `anomaly_count ≥ 10` (here 10 of 85 rows, 11.8%).

**Narrative:**

> This batch of 85 cleaned transactions totals ₹1,339,923.00 and $74,185.14 across
> five accounts, dominated by IRCTC, Jio Recharge, and Flipkart. Ten anomalies were
> detected: five extreme statistical outliers (each roughly 15–20× the account's
> typical spend) and five USD charges on Zomato — a domestic-only merchant — which
> together point to likely data-entry or fraud issues. Given the number and
> magnitude of these anomalies, the batch is rated **high** risk and warrants
> manual review.

---

<sub>Generated from `data/transactions.csv` using the logic in `app/pipeline/`.
Merchant totals reconcile to ₹1,339,923.00 + $74,185.14 = 1,414,108.14.</sub>
