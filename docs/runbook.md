# NeuroFlow Operations Runbook

This document is for on-call engineers. Each section covers a specific incident type
with diagnostic steps and remediation actions.

---

## Incident 1 — High Query Latency (P95 > 10s)

**Symptom:** Users report slow responses; Grafana `neuroflow_generation_latency_seconds`
p95 bucket is > 10.

**Diagnostic steps:**

1. **Identify the slow span in Jaeger**
   - Open http://jaeger:16686
   - Search by service `neuroflow` and tag `error=true` or sort by duration
   - Find which span is taking longest: `retrieval.pipeline`, `generation.llm_call`, or `evaluation.judge`

2. **Check Redis cache hit rate**
   ```bash
   redis-cli -a $REDIS_PASSWORD info stats | grep keyspace_hits
   redis-cli -a $REDIS_PASSWORD info stats | grep keyspace_misses
   ```
   If hit rate < 30%, embedding cache is cold — expected after restart.

3. **Check Postgres query performance**
   ```sql
   SELECT query, mean_exec_time, calls
   FROM pg_stat_statements
   ORDER BY mean_exec_time DESC LIMIT 10;
   ```
   If HNSW index scan is slow, check `ef_search` parameter:
   ```sql
   SET hnsw.ef_search = 40;  -- default 40, try 20 for lower latency
   ```

4. **Check Groq API latency**
   - Query Prometheus: `rate(neuroflow_generation_latency_seconds_sum[5m]) / rate(neuroflow_generation_latency_seconds_count[5m])`
   - If Groq-side latency: check https://status.groq.com

**Remediation:**
- Flush cold Redis cache: `redis-cli FLUSHDB` (clears rate-limit counters too — use carefully)
- Scale API replicas: `docker compose up --scale api=4`
- Lower `top_k_after_rerank` in pipeline config to reduce LLM reranking calls
- Enable result caching: identical queries within 30min return cached response

---

## Incident 2 — Evaluation Scores Degrading

**Symptom:** Grafana `neuroflow_eval_overall` gauge drops below 0.65; alert fires.

**Diagnostic steps:**

1. **Identify which pipeline and metric is degrading**
   ```sql
   SELECT pr.pipeline_id, AVG(e.faithfulness), AVG(e.answer_relevance),
          AVG(e.context_precision), AVG(e.context_recall), COUNT(*)
   FROM evaluations e JOIN pipeline_runs pr ON pr.id = e.run_id
   WHERE e.evaluated_at > NOW() - INTERVAL '1 hour'
   GROUP BY pr.pipeline_id;
   ```

2. **Check recently ingested documents for quality issues**
   ```sql
   SELECT id, filename, chunk_count, created_at
   FROM documents
   WHERE created_at > NOW() - INTERVAL '24 hours'
   ORDER BY created_at DESC;
   ```
   Low chunk_count for large documents → extraction failure. Check worker logs.

3. **Check MLflow for recent fine-tuning jobs**
   - Open http://mlflow:5000
   - If a fine-tuning job completed in the last 24h, the new model may be underperforming
   - Check `router:models` in Redis: `redis-cli GET router:models`

**Remediation:**
- If caused by a bad fine-tuned model: remove it from Redis router models
  ```bash
  redis-cli -a $REDIS_PASSWORD DEL router:models  # reverts to DEFAULT_MODELS
  ```
- If caused by poor ingestion quality: delete the problematic documents and re-ingest
  ```sql
  DELETE FROM documents WHERE id = 'bad-doc-id';
  -- Re-submit via POST /ingest
  ```
- Increase `training_threshold` in pipeline config from 0.82 to 0.87 to raise quality bar

---

## Incident 3 — LLM Provider Circuit Breaker Open

**Symptom:** GET /health returns `"status": "degraded"` with `"groq": {"state": "open"}`;
queries fail immediately with 503.

**Diagnostic steps:**

1. **Check health endpoint**
   ```bash
   curl http://localhost:8000/health | jq .checks.circuit_breakers
   ```

2. **Check Groq status page**
   - https://status.groq.com — if there's an active incident, wait for recovery

3. **Check error logs**
   ```bash
   docker logs neuroflow-api-1 --tail=50 | grep circuit
   ```

4. **Check circuit breaker state in Redis**
   ```bash
   redis-cli -a $REDIS_PASSWORD GET "circuit:groq"
   ```

**Remediation:**

- **Wait:** Circuit auto-recovers after `recovery_timeout` (60s default). It will
  transition to HALF_OPEN and probe with 3 requests.

- **Manual reset** (if you've confirmed Groq is healthy):
  ```bash
  curl -X POST "http://localhost:8000/admin/circuit-breaker/reset?name=groq" \
    -H "Authorization: Bearer $ADMIN_TOKEN"
  ```

- **Route to Anthropic fallback** (if Groq outage is prolonged):
  Update Redis to promote Anthropic models:
  ```bash
  redis-cli -a $REDIS_PASSWORD SET router:models '[{"name":"claude-3-haiku-20240307","provider":"anthropic",...}]'
  ```

---

## Incident 4 — Ingestion Queue Depth > 100

**Symptom:** POST /ingest returns 503; GET /health shows `queue_depth > 100`.

**Diagnostic steps:**

1. **Check queue depth**
   ```bash
   redis-cli -a $REDIS_PASSWORD LLEN queue:ingest
   ```

2. **Check worker process logs**
   ```bash
   docker logs neuroflow-worker-1 --tail=100
   ```
   Look for repeated errors on the same document_id — stuck job.

3. **Check for stuck documents**
   ```sql
   SELECT id, filename, status, created_at
   FROM documents
   WHERE status = 'processing'
   AND created_at < NOW() - INTERVAL '30 minutes';
   ```

**Remediation:**

- **Restart workers** (clears in-flight jobs back to queue):
  ```bash
  docker compose restart worker
  ```

- **Remove stuck jobs** from queue head (inspect first):
  ```bash
  redis-cli -a $REDIS_PASSWORD LRANGE queue:ingest 0 4  # inspect
  redis-cli -a $REDIS_PASSWORD RPOP queue:ingest          # remove oldest
  ```

- **Scale up workers** for large backlogs:
  ```bash
  docker compose up --scale worker=4
  ```

- **Mark stuck documents as errored** to unblock downstream:
  ```sql
  UPDATE documents SET status='error'
  WHERE status='processing' AND created_at < NOW() - INTERVAL '30 minutes';
  ```

---

## Incident 5 — Database Disk Usage > 80%

**Symptom:** Postgres disk alert fires; `df -h` shows data volume > 80%.

**Diagnostic steps:**

1. **Find largest tables**
   ```sql
   SELECT schemaname, tablename,
          pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
   FROM pg_tables
   WHERE schemaname = 'public'
   ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
   ```
   `chunks` is almost always the largest table (1536-dimensional vectors × many rows).

2. **Check evaluation table growth**
   ```sql
   SELECT DATE(evaluated_at), COUNT(*) FROM evaluations
   GROUP BY 1 ORDER BY 1 DESC LIMIT 14;
   ```

3. **Check for orphaned chunks** (documents that were deleted):
   ```sql
   SELECT COUNT(*) FROM chunks c
   LEFT JOIN documents d ON d.id = c.document_id
   WHERE d.id IS NULL;
   ```

**Remediation:**

- **Run data retention** (deletes old completed runs and evaluations):
  ```sql
  -- Delete pipeline runs older than 90 days (no evaluation attached)
  DELETE FROM pipeline_runs
  WHERE status = 'complete'
    AND created_at < NOW() - INTERVAL '90 days'
    AND id NOT IN (SELECT run_id FROM evaluations);

  -- Delete evaluations older than 180 days
  DELETE FROM evaluations WHERE evaluated_at < NOW() - INTERVAL '180 days';

  -- VACUUM to reclaim space
  VACUUM ANALYZE chunks;
  VACUUM ANALYZE pipeline_runs;
  VACUUM ANALYZE evaluations;
  ```

- **Archive old documents** if specific ingested content is no longer needed:
  ```sql
  UPDATE documents SET status='archived' WHERE created_at < NOW() - INTERVAL '1 year';
  DELETE FROM chunks WHERE document_id IN (
    SELECT id FROM documents WHERE status='archived'
  );
  ```

- **Expand disk** if retention doesn't free enough space:
  Resize the Docker volume or Postgres managed disk in your cloud provider.
