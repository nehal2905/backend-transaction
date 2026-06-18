# AI-Powered Transaction Processing Pipeline

An async backend that ingests a transactions CSV, then runs a multi-stage pipeline
to **clean** the data, **detect anomalies**, **classify** uncategorised rows with an
LLM, and produce an **AI narrative summary** — all behind a thin FastAPI layer with
PostgreSQL persistence and a Celery + Redis job queue. The whole stack boots with a
single `docker compose up`.

---

## Architecture

```
                    ┌──────────────────────────────────────────────┐
   client  ──POST──▶│  FastAPI (api)                               │
   (curl)           │  /jobs/upload  /jobs/{id}/status             │
        ◀──202──────│  /jobs/{id}/results  /jobs                   │
                    └───────┬───────────────────────┬──────────────┘
                            │ save CSV              │ create Job(pending)
                            ▼                        ▼ enqueue process_job.delay()
                 ┌──────────────────┐       ┌────────────────┐
                 │ uploads (volume) │       │  Redis broker  │
                 └────────┬─────────┘       └───────┬────────┘
                          │ read CSV               │ deliver task
                          ▼                         ▼
                    ┌──────────────────────────────────────────────┐
                    │  Celery worker — process_job(job_id)         │
                    │  runner: status=processing                   │
                    │   (a) cleaning  (b) anomaly  (c) classify    │
                    │   (d) summary   (e) finalize → completed     │
                    └───────┬───────────────────────┬──────────────┘
                            │ read/write rows        │ JSON-mode calls
                            ▼                         ▼
                    ┌────────────────┐       ┌────────────────┐
                    │  PostgreSQL    │       │ Gemini 1.5     │
                    │ Job/Txn/Summary│       │ Flash (LLM)    │
                    └────────────────┘       └────────────────┘
```

> A draw.io diagram lives at `docs/architecture.drawio` — export it and link the
> public version here before submitting.

**Layering rationale.** The `app/api/` layer is thin: it only validates input,
enqueues work, and reads results. All real work lives in `app/pipeline/`, which is
pure and unit-testable independent of FastAPI/Celery. The `app/llm/` boundary
isolates the one external dependency that can fail, so all retry/fallback logic
lives in one place.

---

## Tech stack

| Concern | Choice |
|---|---|
| API | FastAPI + Pydantic v2 |
| DB | PostgreSQL 16 (SQLAlchemy 2.x + Alembic) |
| Queue | Celery + Redis |
| LLM | Gemini 1.5 Flash (free tier, JSON mode) |
| LLM transport | `httpx` + `tenacity` (exp backoff, 3 retries) |
| Runtime | Docker + docker compose (4 services) |

---

## Quick start

```bash
# 1. Configure secrets
cp .env.example .env
#    then edit .env and set GEMINI_API_KEY=...
#    (free key: https://aistudio.google.com/app/apikey)

# 2. Boot everything (postgres + redis + api + worker)
docker compose up --build
```

The `api` container runs `alembic upgrade head` automatically before starting, so
the schema is created on a fresh boot with **zero manual steps**.

API docs: <http://localhost:8000/docs>

> No Gemini key? The pipeline still completes: classification batches are marked
> `llm_failed` and the summary falls back to a deterministic narrative/risk level.

---

## Example requests

```bash
# Upload a CSV — returns immediately with a job_id (202)
curl -F "file=@data/transactions.csv" http://localhost:8000/jobs/upload

# Poll status (includes high-level summary once completed)
curl http://localhost:8000/jobs/<job_id>/status

# Full structured results (409 until completed)
curl http://localhost:8000/jobs/<job_id>/results

# List all jobs, newest first — with optional status filter
curl "http://localhost:8000/jobs"
curl "http://localhost:8000/jobs?status=completed"
```

---

## The pipeline (`process_job` → `runner.run_pipeline`)

| Step | Module | What it does |
|---|---|---|
| a. Cleaning | `pipeline/cleaning.py` | Dates → ISO 8601 (explicit `DD-MM-YYYY` vs `YYYY/MM/DD`), strip `$`, uppercase status/currency, blank category → `Uncategorised`, drop exact duplicate rows. Records `row_count_raw` and `row_count_clean`. |
| b. Anomaly | `pipeline/anomaly.py` | Flags `amount > 3× median` (median per **(account_id, currency)** so INR/USD scales never mix) and `USD on a domestic-only merchant` (Swiggy/Ola/IRCTC/…). Multiple reasons join with `; `. |
| c. Classify | `pipeline/classify.py` | LLM categorizes **only** originally-blank rows into 8 fixed labels, **batched** (`LLM_BATCH_SIZE`, default 25), never one call per row. |
| d. Summary | `pipeline/summary.py` | **Single** LLM call over aggregates (not raw rows) → narrative + risk level. Numeric totals are computed locally as ground truth. Persisted as a `JobSummary` row. |
| e. Retries | `llm/client.py` | Every LLM call wrapped in tenacity: `stop_after_attempt(3)` + `wait_exponential`. Exhausted classification batch → `llm_failed=true`, continue. Exhausted summary → deterministic fallback. **LLM failure never fails the job.** |

### Status lifecycle

```
pending ──(worker picks up)──▶ processing ──(a–e ok)──▶ completed
                                   └──(unhandled error)──▶ failed (error_message set)
```

An LLM batch/summary failure is **not** a job failure — it degrades gracefully and
the job still reaches `completed`.

---

## Data model

- **Job** — `filename, file_path, status, row_count_raw, row_count_clean, error_message, created_at, completed_at`
- **Transaction** — all source fields + `is_anomaly, anomaly_reason, llm_category, llm_raw_response, llm_failed` (FK → Job)
- **JobSummary** — `total_spend_inr, total_spend_usd, top_merchants (JSONB), anomaly_count, narrative, risk_level` (1-1 with Job)

ERD: `Job 1──* Transaction` and `Job 1──1 JobSummary`.

---

## Bottlenecks & scale (where it breaks at 100×)

- **Whole file processed in one in-memory task.** 90 rows is fine; 9M rows OOMs the
  worker and one job monopolizes a slot. → Stream/chunk the CSV and fan out into
  per-chunk subtasks (Celery `chord`/`group`), then aggregate.
- **Row-by-row ORM writes.** → Bulk insert (`COPY` / `execute_values`) + PgBouncer
  pooling (api+worker exhaust Postgres connections first at 100×).
- **LLM is the throughput ceiling and cost center.** → Dedicated rate-limited LLM
  queue, async concurrency caps, cache classifications for repeated
  `(merchant, note)` pairs, consider a cheaper/local model at high volume.
- **Single Redis + single Postgres.** → Redis cluster / separate result backend,
  Postgres read replicas for read-heavy `GET /results`, S3 for uploads instead of a
  local volume.
- **Polling is wasteful.** → Webhooks/SSE for completion; idempotency keys on upload.

Trade-off throughout: more moving parts and operational complexity vs. horizontal
scalability — justified only past the volume where the monolith stalls.

---

## Project layout

```
app/
  main.py            FastAPI app + router include + startup
  config.py          pydantic-settings env config
  database.py        engine / SessionLocal / get_db
  celery_app.py      Celery instance (broker/backend)
  models.py          SQLAlchemy: Job, Transaction, JobSummary
  schemas.py         Pydantic request/response models
  enums.py           JobStatus, TxnStatus, Currency, RiskLevel, categories
  storage.py         save/read uploaded CSV on shared volume
  tasks.py           Celery task process_job(job_id)
  api/jobs.py        the 4 endpoints
  pipeline/          cleaning, anomaly, classify, summary, runner
  llm/               client (Gemini, tenacity) + prompts
migrations/          Alembic env + versions
data/transactions.csv  sample input
```
