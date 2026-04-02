# NeuroFlow — Deployment Guide

## Recommended: Railway

Railway supports multi-service deployments, managed Postgres with pgvector, and managed Redis.

### Prerequisites
- Railway account (railway.app)
- Railway CLI: `npm install -g @railway/cli`
- Docker installed locally

---

### Step 1 — Create project

```bash
railway login
railway new neuroflow
```

### Step 2 — Add managed services

In the Railway dashboard:
1. **Add Postgres** — select `pgvector/pgvector:pg16` image
2. **Add Redis** — use Railway's managed Redis plugin
3. **Add MLflow** — deploy from `ghcr.io/mlflow/mlflow:latest`

### Step 3 — Set environment variables

In Railway project settings → Variables, add all variables from `.env.example`:

```bash
railway variables set GROQ_API_KEY=gsk_...
railway variables set OPENAI_API_KEY=sk-...   # embeddings only
railway variables set JWT_SECRET_KEY=$(openssl rand -hex 32)
railway variables set ENVIRONMENT=production
railway variables set LOG_LEVEL=INFO
```

Railway auto-injects `POSTGRES_URL` and `REDIS_URL` from the managed plugins.

### Step 4 — Deploy API

```bash
cd backend
railway up --service api
```

### Step 5 — Deploy worker

```bash
railway up --service worker --start-command "python worker.py"
```

### Step 6 — Deploy frontend

```bash
cd frontend
railway up --service frontend
```

### Step 7 — Run database migrations

```bash
railway run --service api -- python -c "
import asyncio
from db.pool import create_pool, get_pool

async def migrate():
    await create_pool()
    pool = get_pool()
    with open('infra/init/001_schema.sql') as f:
        await pool.execute(f.read())
    print('Migration complete')

asyncio.run(migrate())
"
```

---

## Production Verification Checklist

After deployment, run each check:

```bash
BASE=https://your-app.railway.app

# 1. Health check
curl $BASE/health | jq .

# 2. Ingest a test document
curl -X POST $BASE/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@tests/fixtures/test_doc.pdf"

# 3. Submit a query
curl -X POST $BASE/query \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"What is RAG?","pipeline_id":"YOUR_PIPELINE_ID","stream":true}'

# 4. Check SSE stream
curl -N $BASE/query/{run_id}/stream \
  -H "Authorization: Bearer $TOKEN"

# 5. Check evaluations
curl $BASE/evaluations -H "Authorization: Bearer $TOKEN" | jq .

# 6. Check Prometheus metrics
curl $BASE/metrics | grep neuroflow_queries_total
```

---

## Rollback Procedure

### Rollback API to previous image

```bash
# List recent images
railway images --service api

# Rollback to specific SHA
railway rollback --service api --deployment $PREVIOUS_DEPLOYMENT_ID
```

### Verify rollback succeeded

```bash
curl $BASE/health | jq .status
```

Should return `"ok"` within 30 seconds of rollback.

### Database rollback

NeuroFlow migrations are additive only — no destructive schema changes.
If a migration caused issues, restore from the last Railway Postgres backup:
```bash
railway backup restore --service postgres --backup-id $BACKUP_ID
```

---

## Alternative: Render

1. Connect your GitHub repo to Render
2. Create a **Web Service** for the API: build command `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Create a **Background Worker** for the worker: start `python worker.py`
4. Add **Postgres** and **Redis** from the Render dashboard
5. Set all environment variables in the Render dashboard
