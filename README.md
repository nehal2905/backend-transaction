# AI-Powered Transaction Processing Pipeline

An asynchronous backend system that ingests transaction CSV files, processes them through a multi-stage pipeline, detects anomalies, classifies uncategorised transactions using Google Gemini, and generates an AI-powered spending summary.

The system is built using FastAPI, PostgreSQL, Redis, Celery, Docker, and Google Gemini 2.5 Flash.

---

## Features

* CSV upload and asynchronous processing
* Data cleaning and normalization
* Statistical anomaly detection
* Currency mismatch anomaly detection
* LLM-based transaction categorization
* AI-generated spending narrative
* PostgreSQL persistence
* Celery + Redis background processing
* Graceful degradation when LLM services fail
* Single-command deployment using Docker Compose

---

## Architecture

![Architecture Diagram](docs/architecture.png)

### Request Flow

1. Client uploads a CSV file.
2. FastAPI validates the request and creates a Job record.
3. A Celery task is queued through Redis.
4. The worker executes the processing pipeline:

   * Data Cleaning
   * Anomaly Detection
   * LLM Classification
   * LLM Narrative Summary
   * Result Persistence
5. Results are stored in PostgreSQL.
6. Client polls the API for status and results.

---

## Tech Stack

| Component        | Technology              |
| ---------------- | ----------------------- |
| API              | FastAPI                 |
| Database         | PostgreSQL 16           |
| ORM              | SQLAlchemy 2.x          |
| Migrations       | Alembic                 |
| Queue            | Celery                  |
| Broker           | Redis                   |
| LLM              | Google Gemini 2.5 Flash |
| HTTP Client      | httpx                   |
| Retry Logic      | Tenacity                |
| Containerization | Docker + Docker Compose |

---

## Repository

```bash
git clone https://github.com/nehal2905/backend-transaction.git
cd backend-transaction
```

---

## Quick Start

### 1. Configure Environment

Create a `.env` file:

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/transactions

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

GEMINI_API_KEY=YOUR_API_KEY
GEMINI_MODEL=gemini-2.5-flash

POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=transactions
```

### 2. Start Everything

```bash
docker compose up --build
```

The following services start automatically:

* FastAPI API
* PostgreSQL
* Redis
* Celery Worker

Database migrations are applied automatically during startup using:

```bash
alembic upgrade head
```

### Running Without a Gemini Key

The application still runs end-to-end without a Gemini API key.

In that case:

* Classification batches are marked `llm_failed=true`
* Narrative generation falls back to deterministic summaries
* Jobs still complete successfully

---

## API Documentation

Swagger UI:

```text
http://localhost:8000/docs
```

---

## API Endpoints

### Upload CSV

```http
POST /jobs/upload
```

Example:

```bash
curl -F "file=@data/transactions.csv" \
http://localhost:8000/jobs/upload
```

Response:

```json
{
  "job_id": "f48189e3-d5bd-4b26-b5c1-7663a0ece0b0",
  "status": "pending"
}
```

---

### Job Status

```http
GET /jobs/{job_id}/status
```

Possible states:

* pending
* processing
* completed
* failed

Returns high-level summary information after completion.

---

### Job Results

```http
GET /jobs/{job_id}/results
```

Returns:

* Cleaned transactions
* Detected anomalies
* Category breakdown
* AI-generated summary

---

### List Jobs

```http
GET /jobs
```

Optional filter:

```http
GET /jobs?status=completed
```

---

## Processing Pipeline

### 1. Data Cleaning

Implemented in:

```text
app/pipeline/cleaning.py
```

Performs:

* Date normalization to ISO-8601
* Currency symbol stripping
* Currency normalization
* Status normalization
* Missing category handling
* Exact duplicate removal

---

### 2. Anomaly Detection

Implemented in:

```text
app/pipeline/anomaly.py
```

#### Statistical Outliers

Transactions are flagged when:

```text
amount > 3 × median(account_id, currency)
```

Median is calculated per `(account_id, currency)` to avoid mixing INR and USD distributions.

#### Currency Mismatch Detection

Transactions are flagged when:

```text
currency = USD
AND merchant is domestic-only
```

Examples:

* Swiggy
* Ola
* Zomato
* IRCTC
* Flipkart
* Jio
* Airtel
* MakeMyTrip

---

### 3. LLM Classification

Implemented in:

```text
app/pipeline/classify.py
```

Only transactions with missing categories are sent to Gemini.

Supported categories:

* Food
* Shopping
* Travel
* Transport
* Utilities
* Cash Withdrawal
* Entertainment
* Other

Classification requests are batched to minimize API calls.

---

### 4. AI Narrative Summary

Implemented in:

```text
app/pipeline/summary.py
```

A single Gemini call generates:

* Total spend by currency
* Top merchants
* Anomaly count
* Spending narrative
* Risk level

Possible risk levels:

* Low
* Medium
* High

---

### 5. Retry & Failure Handling

Implemented in:

```text
app/llm/client.py
```

Every Gemini request uses:

```text
stop_after_attempt(3)
wait_exponential()
```

If classification fails:

```text
llm_failed = true
```

and processing continues.

If summary generation fails:

A deterministic fallback summary is generated.

The job never fails solely because the LLM is unavailable.

---

## Data Model

### Job

Stores:

* status
* filename
* file path
* row counts
* timestamps
* error messages

### Transaction

Stores:

* original transaction fields
* anomaly metadata
* LLM classification data

### JobSummary

Stores:

* total spend by currency
* top merchants
* anomaly count
* narrative
* risk level

Relationships:

```text
Job 1 ─── * Transaction
Job 1 ─── 1 JobSummary
```

---

## Example Dataset Results

Latest run using the provided sample dataset:

| Metric             | Value               |
| ------------------ | ------------------- |
| Raw Rows           | 95                  |
| Clean Rows         | 85                  |
| Duplicates Removed | 10                  |
| Missing txn_id     | 4                   |
| Missing Categories | 15 → 13 after dedup |
| Anomalies          | 15                  |
| Risk Level         | Medium              |
| Total INR Spend    | ₹1,339,923.00       |
| Total USD Spend    | $74,185.14          |

### Anomaly Breakdown

* 5 Statistical Outliers
* 10 Currency Mismatches

Examples:

* USD transaction on Zomato
* USD transaction on MakeMyTrip
* Transactions exceeding 3× account median

---

## Scale Considerations

Current implementation is optimized for assignment-scale workloads.

At significantly larger traffic volumes:

### Current Bottlenecks

* Entire CSV processed within a single worker task
* Row-by-row ORM inserts
* Shared Redis broker/backend
* Polling-based completion tracking
* External LLM throughput limits

### Future Improvements

* Chunked CSV processing
* Celery groups/chords
* Bulk inserts
* PgBouncer connection pooling
* Dedicated LLM queue
* Response caching
* S3-based object storage
* Webhooks or Server-Sent Events

Trade-off: increased operational complexity in exchange for horizontal scalability.

---

## Project Structure

```text
app/
├── api/
├── llm/
├── pipeline/
├── main.py
├── tasks.py
├── models.py
├── schemas.py
├── config.py
├── database.py
├── celery_app.py

migrations/
data/
docs/
docker-compose.yml
Dockerfile
README.md
```

---

## Author

Backend Developer Internship Assignment Submission

Akula Nehal
