# ADR 001 — Vector Store: pgvector over Pinecone / Weaviate / Qdrant

**Status:** Accepted  
**Date:** 2024-01-01

---

## Context

NeuroFlow needs a vector store to persist chunk embeddings (1536 dimensions) and serve
approximate nearest-neighbour queries at query time. Options evaluated:

| Option | Hosting | Cost | Operational complexity |
|--------|---------|------|----------------------|
| Pinecone | Managed SaaS | $70+/mo for production tier | Low — no infra |
| Weaviate | Self-hosted or cloud | Free self-hosted | Medium — separate service |
| Qdrant | Self-hosted or cloud | Free self-hosted | Medium — separate service |
| pgvector | Extension on Postgres | Free — already running | None — same DB |

NeuroFlow already requires Postgres for all relational data (documents, runs,
evaluations, pipelines). Every query requires both a vector similarity search AND
relational joins (chunk → document → pipeline). An external vector store would require:
1. A vector query to the external store
2. A separate relational query to Postgres to join document/pipeline metadata
3. Result merging in application code

This adds network round-trips, operational complexity, a second service to run and monitor,
and a second backup/restore procedure.

---

## Decision

Use **pgvector** with an HNSW index on `chunks.embedding`.

```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

Hybrid search is implemented entirely in SQL:
```sql
-- Dense: pgvector cosine similarity
SELECT *, 1 - (embedding <=> $1::vector) AS score FROM chunks ORDER BY embedding <=> $1 LIMIT 20;

-- Sparse: PostgreSQL full-text search on same table
SELECT *, ts_rank_cd(...) AS score FROM chunks WHERE to_tsvector(...) @@ plainto_tsquery(...);
```

Both queries hit the same table in the same transaction. No application-level result merging.

---

## Consequences

**Positive:**
- Zero additional infrastructure — pgvector is a Postgres extension
- Native SQL joins between vectors and relational data (chunk → document → pipeline)
- Single backup/restore, single monitoring target, single connection pool
- HNSW index provides sub-10ms query latency at our scale (<10M chunks)
- Full ACID guarantees: ingestion + vector write are a single transaction

**Negative:**
- Not suitable for >100M vectors at production scale — would need to migrate to Qdrant
- Cannot shard across multiple nodes without Citus or similar
- No built-in multi-tenancy at the vector layer (mitigated by RLS policies)
- HNSW index rebuild is expensive when adding large batches

**Migration path:** If vector count exceeds 50M, migrate embeddings to Qdrant while keeping
all relational data in Postgres. The `retriever.py` interface is already abstracted —
swap `_dense_retrieval` to call Qdrant client instead of asyncpg.
