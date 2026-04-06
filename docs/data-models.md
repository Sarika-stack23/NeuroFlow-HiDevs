# NeuroFlow — Data Models

## documents
Tracks each ingested source file or URL.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| filename | TEXT | Original filename or URL |
| source_type | VARCHAR(20) | pdf / docx / image / csv / url / text |
| content_hash | TEXT UNIQUE | SHA-256 of file bytes (deduplication key) |
| metadata | JSONB | Extractor-specific metadata |
| pipeline_id | UUID | Optional pipeline association |
| status | VARCHAR(20) | queued / processing / complete / error / archived |
| chunk_count | INT | Populated after ingestion completes |
| created_at | TIMESTAMPTZ | Row creation time |

---

## chunks
Individual text segments with vector embeddings.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| document_id | UUID FK | References documents.id (CASCADE DELETE) |
| content | TEXT | Raw text of the chunk |
| embedding | vector(1536) | OpenAI text-embedding-3-small vector |
| chunk_index | INT | Position within parent document |
| token_count | INT | tiktoken-counted tokens |
| metadata | JSONB | page_number, heading, heading_level, etc. |
| created_at | TIMESTAMPTZ | Row creation time |

**Indexes:**
- `HNSW (embedding vector_cosine_ops)` — approximate nearest-neighbour search
- `GIN (to_tsvector('english', content))` — full-text search
- `GIN (metadata)` — metadata filter queries
- `BTree (document_id)` — join performance

---

## pipelines
Named, versioned RAG pipeline configurations.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| name | TEXT UNIQUE | Human-readable name |
| config | JSONB | Full PipelineConfig schema |
| version | INT | Increments on each PATCH |
| status | VARCHAR(20) | active / archived |
| created_at | TIMESTAMPTZ | Row creation time |

---

## pipeline_versions
Historical configs preserved on every pipeline update.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| pipeline_id | UUID FK | References pipelines.id |
| version | INT | Version number at time of archival |
| config | JSONB | Archived config snapshot |
| created_at | TIMESTAMPTZ | When this version was superseded |

---

## pipeline_runs
Each RAG query execution.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated (also the run_id in SSE) |
| pipeline_id | UUID FK | References pipelines.id |
| pipeline_version | INT | Which version was used |
| query | TEXT | Raw user query |
| retrieved_chunk_ids | UUID[] | Chunk IDs used in context window |
| generation | TEXT | Full LLM response |
| latency_ms | INT | End-to-end latency |
| input_tokens | INT | LLM input tokens |
| output_tokens | INT | LLM output tokens |
| model_used | TEXT | e.g. llama-3.3-70b-versatile |
| status | VARCHAR(20) | pending / running / complete / error |
| metadata | JSONB | Citations, chain-of-thought, flags |
| created_at | TIMESTAMPTZ | Query submission time |

---

## evaluations
Automated quality scores for each pipeline run.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| run_id | UUID FK | References pipeline_runs.id |
| faithfulness | FLOAT | 0.0–1.0 — claims grounded in context |
| answer_relevance | FLOAT | 0.0–1.0 — addresses the question |
| context_precision | FLOAT | 0.0–1.0 — retrieved chunks were useful |
| context_recall | FLOAT | 0.0–1.0 — answer attributable to context |
| overall_score | FLOAT | Weighted sum (0.35/0.30/0.20/0.15) |
| judge_model | TEXT | Model that scored this evaluation |
| user_rating | INT (1-5) | Optional human feedback rating |
| metadata | JSONB | calibration_needed flag, etc. |
| evaluated_at | TIMESTAMPTZ | When evaluation completed |

---

## training_pairs
High-quality (query, answer) pairs for fine-tuning.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| run_id | UUID FK | Source pipeline_run |
| system_prompt | TEXT | System prompt used in original run |
| user_message | TEXT | Query + context as sent to LLM |
| assistant_message | TEXT | Generated answer |
| quality_score | FLOAT | overall_score at extraction time |
| included_in_job | UUID | finetune_jobs.id when extracted |
| created_at | TIMESTAMPTZ | When pair was created |

---

## finetune_jobs
Fine-tuning job tracking.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| provider_job_id | TEXT | Provider's job ID (when available) |
| base_model | TEXT | Starting model name |
| status | VARCHAR(20) | pending / submitted / training / succeeded / failed |
| training_pair_count | INT | Number of training examples |
| mlflow_run_id | TEXT | MLflow run for experiment tracking |
| metrics | JSONB | training_loss, validation_loss, trained_tokens |
| created_at | TIMESTAMPTZ | Job submission time |
| completed_at | TIMESTAMPTZ | Job completion time |

---

## api_clients
Client credentials for JWT authentication.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID PK | Auto-generated |
| client_id | TEXT UNIQUE | Human-readable client identifier |
| client_secret_hash | TEXT | bcrypt hash of the secret |
| scopes | TEXT[] | e.g. {query, ingest, admin} |
| created_at | TIMESTAMPTZ | When client was registered |
