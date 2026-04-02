# NeuroFlow — System Architecture

## Overview

NeuroFlow is a production multi-modal RAG orchestration platform. It accepts raw documents
in multiple formats, extracts and chunks their content, stores embeddings in pgvector, and
serves grounded, cited answers via configurable pipelines. Every generation is automatically
evaluated, and high-quality generations become fine-tuning training data.

---

## Subsystem 1 — Ingestion

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Ingestion Subsystem                           │
│                                                                       │
│  POST /ingest                                                         │
│      │                                                                │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  API Layer                                                │        │
│  │  1. Validate file type (MIME + magic bytes)               │        │
│  │  2. Compute SHA-256 content hash                          │        │
│  │  3. Check documents.content_hash → return if duplicate   │        │
│  │  4. INSERT documents row (status=queued)                  │        │
│  │  5. LPUSH queue:ingest {document_id, file_path, type}    │        │
│  │  6. Return {document_id, status: queued}  ← immediately  │        │
│  └──────────────────────────────────────────────────────────┘        │
│                                                                       │
│  [Worker Process — separate container]                                │
│      │                                                                │
│      ▼  BRPOP queue:ingest                                           │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Extractor (per source_type)                              │        │
│  │  ┌──────┐ ┌──────┐ ┌───────┐ ┌─────┐ ┌─────┐           │        │
│  │  │ PDF  │ │ DOCX │ │ Image │ │ CSV │ │ URL │           │        │
│  │  │pypdf │ │docx  │ │Vision │ │pand │ │traf │           │        │
│  │  │plumb │ │      │ │LLM+   │ │as   │ │icat │           │        │
│  │  │OCR   │ │      │ │OCR    │ │     │ │ura  │           │        │
│  │  └──────┘ └──────┘ └───────┘ └─────┘ └─────┘           │        │
│  │       │                                                   │        │
│  │       ▼  list[ExtractedPage]                             │        │
│  │  Chunker (auto-select strategy)                           │        │
│  │  ┌────────────┐ ┌──────────┐ ┌──────────────┐           │        │
│  │  │ fixed_size │ │ semantic │ │ hierarchical │           │        │
│  │  │ 512 tokens │ │ cosine   │ │ heading-     │           │        │
│  │  │ 64 overlap │ │ shifts   │ │ aware        │           │        │
│  │  └────────────┘ └──────────┘ └──────────────┘           │        │
│  │       │                                                   │        │
│  │       ▼  list[Chunk]                                     │        │
│  │  Embed (Groq → OpenAI text-embedding-3-small)            │        │
│  │       │                                                   │        │
│  │       ▼  list[vector(1536)]                              │        │
│  │  INSERT INTO chunks (content, embedding, metadata)       │        │
│  │  UPDATE documents SET status=complete, chunk_count=N     │        │
│  └──────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

**Data flow:** File upload → SHA-256 dedup check → async queue → extract → chunk → embed → pgvector

---

## Subsystem 2 — Retrieval

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Retrieval Subsystem                           │
│                                                                       │
│  User Query: "How does attention work in transformers?"              │
│      │                                                                │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Query Processor                                          │        │
│  │  • Query expansion: generate 2-3 alternative phrasings   │        │
│  │  • Metadata filter extraction: detect year/topic filters │        │
│  │  • Query type classification: factual/analytical/...     │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼  asyncio.gather → parallel retrieval                         │
│  ┌───────────┐  ┌──────────────┐  ┌────────────────────┐           │
│  │  Dense    │  │   Sparse     │  │  Metadata Filter   │           │
│  │ Retrieval │  │  Retrieval   │  │   Retrieval        │           │
│  │           │  │              │  │                    │           │
│  │ embed(q)  │  │ plainto_     │  │ chunks.metadata    │           │
│  │ <=>       │  │ tsquery +    │  │ @> filter::jsonb   │           │
│  │ HNSW idx  │  │ ts_rank_cd   │  │ + vector sort      │           │
│  │ top-20    │  │  top-20      │  │   top-20           │           │
│  └───────────┘  └──────────────┘  └────────────────────┘           │
│       │               │                    │                         │
│       └───────────────┴────────────────────┘                        │
│                       │                                              │
│                       ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Reciprocal Rank Fusion (RRF, k=60)                      │        │
│  │  score(chunk) = Σ 1/(k + rank_i)  for each list it      │        │
│  │  appears in — chunks in multiple lists get boosted       │        │
│  └──────────────────────────────────────────────────────────┘        │
│                       │  top-40 fused results                        │
│                       ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Cross-Encoder Reranker                                   │        │
│  │  Score (query, chunk) pairs via LLM — relevance 0-10    │        │
│  │  Runs in parallel via asyncio.gather                     │        │
│  └──────────────────────────────────────────────────────────┘        │
│                       │  top-K reranked chunks                       │
│                       ▼                                              │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Context Assembler                                        │        │
│  │  • Format: [Source N — doc.pdf, page 3]\n{content}       │        │
│  │  • Token budget: 4000 tokens (configurable)              │        │
│  │  • Returns: context_string + {chunks_used, sources}      │        │
│  └──────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Subsystem 3 — Generation

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Generation Subsystem                           │
│                                                                       │
│  context_window + query                                              │
│      │                                                                │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Prompt Builder                                           │        │
│  │  • Base system prompt (citation-required instructions)   │        │
│  │  • Per-query-type addition (factual/analytical/...)      │        │
│  │  • Context injected in <context> tags                    │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼  INSERT pipeline_runs (status=running)                       │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  ModelRouter → select provider + model                   │        │
│  │  Criteria: task_type, cost, vision, context_length       │        │
│  │  Default: llama-3.3-70b-versatile (Groq)                │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼  provider.stream(messages)                                   │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  SSE Stream  GET /query/{run_id}/stream                  │        │
│  │  Events:                                                  │        │
│  │    {"type":"retrieval_start"}                            │        │
│  │    {"type":"retrieval_complete","chunk_count":8}         │        │
│  │    {"type":"token","delta":"Based"}                      │        │
│  │    {"type":"token","delta":" on"}   × N tokens           │        │
│  │    {"type":"done","citations":[...]}                     │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼  after stream complete                                        │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Post-processing                                          │        │
│  │  • Parse [Source N] citations → map to chunk_ids         │        │
│  │  • Flag hallucinated citations (N > chunks_used)         │        │
│  │  • UPDATE pipeline_runs (generation, tokens, latency)   │        │
│  │  • LPUSH queue:evaluate {run_id, query, answer}         │        │
│  └──────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Subsystem 4 — Evaluation

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Evaluation Subsystem                            │
│                                                                       │
│  queue:evaluate  →  EvaluationJudge                                 │
│                                                                       │
│  asyncio.gather (all metrics in parallel):                          │
│                                                                       │
│  ┌──────────────────┐  ┌──────────────────┐                         │
│  │  Faithfulness    │  │ Answer Relevance  │                         │
│  │                  │  │                  │                         │
│  │ Extract claims   │  │ Generate 3-5     │                         │
│  │ from answer      │  │ questions the    │                         │
│  │ → verify each    │  │ answer fits →    │                         │
│  │ claim vs context │  │ embed similarity │                         │
│  │ score: 0.0–1.0  │  │ vs orig query    │                         │
│  └──────────────────┘  └──────────────────┘                         │
│                                                                       │
│  ┌──────────────────┐  ┌──────────────────┐                         │
│  │ Context Precision│  │ Context Recall   │                         │
│  │                  │  │                  │                         │
│  │ Per chunk: was   │  │ Per answer sent: │                         │
│  │ this useful?     │  │ attributable to  │                         │
│  │ Weighted by rank │  │ retrieved chunks?│                         │
│  └──────────────────┘  └──────────────────┘                         │
│                │                 │                                    │
│                └────────┬────────┘                                   │
│                         ▼                                            │
│           overall = 0.35×F + 0.30×AR + 0.20×CP + 0.15×CR           │
│                         │                                            │
│                         ▼                                            │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  INSERT evaluations row                                   │        │
│  │  IF overall > 0.82 AND faithfulness > 0.8:               │        │
│  │      INSERT training_pairs                               │        │
│  │  PUBLISH evaluations:new → Redis pub/sub → SSE feed      │        │
│  └──────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Subsystem 5 — Fine-Tuning

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Fine-Tuning Subsystem                           │
│                                                                       │
│  POST /finetune/jobs                                                  │
│      │                                                                │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Training Pair Extraction                                 │        │
│  │  SELECT FROM training_pairs                              │        │
│  │  WHERE quality_score >= 0.82                             │        │
│  │    AND included_in_job IS NULL                           │        │
│  │    AND user_rating != 1 OR 2                             │        │
│  │                                                           │        │
│  │  Validation filters:                                     │        │
│  │  • Token count 50–2000                                   │        │
│  │  • Must contain [Source N] citation                      │        │
│  │  • Faithfulness > 0.8                                    │        │
│  │  • No PII (email, phone patterns)                        │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │  list[validated_pairs]                                        │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Write JSONL  training_data/{job_id}.jsonl               │        │
│  │  {"messages":[                                           │        │
│  │    {"role":"system","content":"..."},                    │        │
│  │    {"role":"user","content":"[Context]...[Q]..."},       │        │
│  │    {"role":"assistant","content":"Based on [Source 1]"} │        │
│  │  ]}                                                      │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼                                                                │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  MLflow Experiment Tracking                               │        │
│  │  mlflow.log_params(base_model, pair_count, avg_quality)  │        │
│  │  mlflow.log_artifact(jsonl_path)                         │        │
│  │  mlflow.register_model(...)                              │        │
│  └──────────────────────────────────────────────────────────┘        │
│      │                                                                │
│      ▼  (when Groq fine-tuning API is available)                    │
│  ┌──────────────────────────────────────────────────────────┐        │
│  │  Submit job → poll status → on success:                  │        │
│  │  • UPDATE finetune_jobs status=succeeded                 │        │
│  │  • UPDATE Redis router:models (add fine-tuned entry)    │        │
│  │  • ModelRouter now auto-routes to fine-tuned model       │        │
│  └──────────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
```
