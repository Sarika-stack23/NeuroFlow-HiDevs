# NeuroFlow — API Contracts

All endpoints except `/health` and `/metrics` require `Authorization: Bearer {token}`.

---

## POST /auth/token
Get JWT access token.

**Request:**
```json
{ "client_id": "string", "client_secret": "string" }
```
**Response:**
```json
{ "access_token": "eyJ...", "token_type": "bearer", "expires_in": 3600 }
```
**Errors:** `401` Invalid credentials
**Auth:** None | **Rate limit:** 10/min/IP

---

## POST /ingest
Ingest a file. Multipart form-data with `file` field.

**Request:** `multipart/form-data` — field `file` (binary) + optional `pipeline_id`

**Response:**
```json
{ "document_id": "uuid", "status": "queued", "duplicate": false }
```
**Errors:** `413` File too large | `415` Unsupported type | `503` Queue full
**Auth:** scope `ingest` | **Rate limit:** 10/hour/IP

---

## POST /ingest/url
Ingest a web URL.

**Request:**
```json
{ "url": "https://example.com/article", "pipeline_id": "uuid (optional)" }
```
**Response:** Same as POST /ingest
**Errors:** `400` Private/loopback URL (SSRF protection)
**Auth:** scope `ingest`

---

## GET /documents/{document_id}
Get document status and metadata.

**Response:**
```json
{
  "id": "uuid", "filename": "report.pdf", "source_type": "pdf",
  "status": "complete", "chunk_count": 42,
  "content_hash": "sha256...", "created_at": "2024-01-15T10:00:00Z"
}
```
**Errors:** `404` Not found
**Auth:** Bearer

---

## POST /query
Submit a RAG query. Returns a `run_id` for streaming.

**Request:**
```json
{ "query": "string", "pipeline_id": "uuid", "stream": true, "temperature": 0.3 }
```
**Response:**
```json
{ "run_id": "uuid", "status": "pending" }
```
**Auth:** scope `query` | **Rate limit:** 60/min/IP

---

## GET /query/{run_id}/stream
SSE stream for a query run. Connect after POST /query.

**Response:** `text/event-stream`
```
data: {"type":"retrieval_start"}
data: {"type":"retrieval_complete","chunk_count":8,"sources":["doc.pdf"]}
data: {"type":"token","delta":"Based"}
data: {"type":"token","delta":" on"}
data: {"type":"done","run_id":"uuid","citations":[{"source":"[Source 1]","chunk_id":"uuid","document":"doc.pdf","page":3}]}
```
**Errors:** `404` Run not found | Keepalive ping every 15s
**Auth:** Bearer

---

## GET /evaluations
Paginated evaluation results.

**Query params:** `page`, `page_size`, `pipeline_id`, `min_score`

**Response:**
```json
[{
  "id": "uuid", "run_id": "uuid", "faithfulness": 0.91,
  "answer_relevance": 0.87, "context_precision": 0.82,
  "context_recall": 0.79, "overall_score": 0.86,
  "user_rating": 5, "evaluated_at": "2024-01-15T10:05:00Z"
}]
```
**Auth:** Bearer

---

## GET /evaluations/aggregate
Rolling 24h quality metrics per pipeline.

**Response:**
```json
[{
  "pipeline_id": "uuid", "faithfulness": 0.83,
  "answer_relevance": 0.81, "overall_score": 0.80, "eval_count": 142
}]
```
**Auth:** Bearer

---

## GET /evaluations/stream
SSE stream — emits new evaluation events in real-time.

**Response:** `text/event-stream` — each event is a full evaluation JSON object.
**Auth:** Bearer

---

## PATCH /runs/{run_id}/rating
Submit user feedback rating.

**Request:** `{ "rating": 1-5 }`
**Response:** `{ "status": "ok" }`
**Auth:** Bearer

---

## POST /pipelines
Create a named pipeline configuration.

**Request:**
```json
{
  "name": "legal-research-v1",
  "config": {
    "name": "legal-research-v1",
    "ingestion": { "chunking_strategy": "hierarchical", "chunk_size_tokens": 400 },
    "retrieval": { "dense_k": 30, "top_k_after_rerank": 8 },
    "generation": { "temperature": 0.2 },
    "evaluation": { "auto_evaluate": true }
  }
}
```
**Response:** `{ "pipeline_id": "uuid", "name": "...", "version": 1 }`
**Errors:** `422` Invalid config schema
**Auth:** scope `admin`

---

## GET /pipelines
List all active pipelines with summary metrics.

**Auth:** Bearer

---

## PATCH /pipelines/{id}
Update pipeline config. Creates a new version — old config preserved.

**Auth:** scope `admin`

---

## GET /pipelines/{id}/runs
Paginated run history for a pipeline.

**Query params:** `page`, `page_size`
**Auth:** Bearer

---

## GET /pipelines/{id}/analytics
Aggregate statistics: latency percentiles, cost, quality scores.

**Response:**
```json
{
  "latency": { "p50": 1200, "p95": 3800, "p99": 5200, "total_runs": 842 },
  "quality": { "faithfulness": 0.84, "overall_score": 0.81 }
}
```
**Auth:** Bearer

---

## POST /pipelines/compare
Run a query through two pipelines simultaneously.

**Request:**
```json
{ "query": "string", "pipeline_a_id": "uuid", "pipeline_b_id": "uuid" }
```
**Response:**
```json
{
  "query": "...",
  "pipeline_a": { "run_id": "uuid", "generation": "...", "total_latency_ms": 1450, "chunks_used": 6 },
  "pipeline_b": { "run_id": "uuid", "generation": "...", "total_latency_ms": 1820, "chunks_used": 8 }
}
```
**Auth:** Bearer

---

## POST /finetune/jobs
Trigger training pair extraction and fine-tuning job submission.

**Query params:** `base_model` (default: `llama-3.1-8b-instant`)
**Response:**
```json
{ "job_id": "uuid", "status": "submitted", "training_pair_count": 47, "mlflow_run_id": "..." }
```
**Auth:** scope `admin`

---

## GET /finetune/jobs/{id}
Fine-tuning job status and metrics.

**Response:**
```json
{
  "id": "uuid", "base_model": "llama-3.1-8b-instant", "status": "submitted",
  "training_pair_count": 47, "mlflow_run_id": "abc123", "created_at": "..."
}
```
**Auth:** Bearer

---

## GET /finetune/training-data/preview
Preview 5 sample training pairs without submitting a job.

**Auth:** Bearer

---

## GET /health
System health — no auth required.

**Response:**
```json
{
  "status": "ok",
  "checks": {
    "postgres": { "status": "ok" },
    "redis": { "status": "ok" },
    "mlflow": { "status": "ok" },
    "circuit_breakers": { "groq": { "state": "closed", "failures": 0 } },
    "queue_depth": 3
  }
}
```
`status` = `ok` | `degraded` | `critical`

---

## GET /metrics
Prometheus metrics — no auth required.

Returns Prometheus text format with all custom `neuroflow_*` metrics.
