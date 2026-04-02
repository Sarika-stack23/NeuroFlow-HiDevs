"""POST /query and GET /query/{run_id}/stream — RAG query with SSE streaming."""
import asyncio
import json
import uuid
from typing import Annotated

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from api.auth import get_current_user, require_scope
from config import settings
from db.pool import get_pool
from monitoring.metrics import queries_total
from providers.base import RoutingCriteria
from providers.router import get_router
from resilience.rate_limiter import rate_limit

router = APIRouter()
logger = structlog.get_logger()


class QueryRequest(BaseModel):
    query: str
    pipeline_id: str
    stream: bool = True
    temperature: float = 0.3


class QueryResponse(BaseModel):
    run_id: str
    status: str


@router.post("/query", response_model=QueryResponse, tags=["Query"])
async def submit_query(
    body: QueryRequest,
    user: dict = Depends(require_scope("query")),
    _=Depends(rate_limit(60, 60, "query")),
):
    """Submit a RAG query. Returns run_id. Connect to /query/{run_id}/stream for SSE."""
    pool = get_pool()

    # Verify pipeline exists
    pipeline = await pool.fetchrow("SELECT id, config FROM pipelines WHERE id = $1 AND status='active'", body.pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    run_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO pipeline_runs (id, pipeline_id, query, status)
           VALUES ($1, $2, $3, 'pending')""",
        run_id, body.pipeline_id, body.query,
    )

    # Enqueue generation job
    r = aioredis.from_url(settings.redis_url)
    await r.set(
        f"query:{run_id}",
        json.dumps({"query": body.query, "pipeline_id": body.pipeline_id, "run_id": run_id}),
        ex=3600,
    )
    await r.aclose()

    return QueryResponse(run_id=run_id, status="pending")


@router.get("/query/{run_id}/stream", tags=["Query"])
async def stream_query(run_id: str, user: dict = Depends(get_current_user)):
    """SSE endpoint — streams retrieval events, tokens, and final citations."""

    async def event_generator():
        pool = get_pool()
        r = aioredis.from_url(settings.redis_url)

        job_raw = await r.get(f"query:{run_id}")
        if not job_raw:
            yield {"data": json.dumps({"type": "error", "message": "Run not found"})}
            return

        job = json.loads(job_raw)
        query = job["query"]
        pipeline_id = job["pipeline_id"]

        pipeline_row = await pool.fetchrow("SELECT config FROM pipelines WHERE id = $1", pipeline_id)
        config = json.loads(pipeline_row["config"]) if pipeline_row else {}
        retrieval_cfg = config.get("retrieval", {})

        # ── Retrieval ──────────────────────────────────────────────
        yield {"data": json.dumps({"type": "retrieval_start"})}

        from pipelines.retrieval.retriever import Retriever
        retriever = Retriever()
        chunks = await retriever.retrieve(query, k=retrieval_cfg.get("dense_k", 20))

        sources = list({c["document_name"] for c in chunks[:5]})
        yield {"data": json.dumps({"type": "retrieval_complete", "chunk_count": len(chunks), "sources": sources})}

        # ── Context assembly ───────────────────────────────────────
        from pipelines.retrieval.context_assembler import assemble_context
        context, context_meta = assemble_context(chunks, max_tokens=config.get("generation", {}).get("max_context_tokens", 4000))

        # ── Prompt build ───────────────────────────────────────────
        from pipelines.generation.prompt_builder import build_prompt
        messages = build_prompt(query=query, context=context, query_type="factual")

        # ── LLM streaming ──────────────────────────────────────────
        router_inst = get_router()
        criteria = RoutingCriteria(task_type="rag_generation")
        provider, model_name = await router_inst.route(criteria)

        full_response = ""
        import time
        t0 = time.time()

        try:
            async for token in provider.stream(messages):
                full_response += token
                yield {"data": json.dumps({"type": "token", "delta": token})}

            # ── Save run ───────────────────────────────────────────
            latency_ms = int((time.time() - t0) * 1000)
            chunk_ids = [str(c["id"]) for c in chunks]
            await pool.execute(
                """UPDATE pipeline_runs SET generation=$1, model_used=$2,
                   latency_ms=$3, retrieved_chunk_ids=$4, status='complete'
                   WHERE id=$5""",
                full_response, model_name, latency_ms,
                chunk_ids, run_id,
            )

            # ── Citation parsing ───────────────────────────────────
            import re
            citations = []
            for match in re.finditer(r"\[Source (\d+)\]", full_response):
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(chunks):
                    c = chunks[idx]
                    citations.append({
                        "source": match.group(0),
                        "chunk_id": str(c["id"]),
                        "document": c.get("document_name", ""),
                        "page": c.get("page_number"),
                    })

            queries_total.labels(pipeline_id=pipeline_id, status="success").inc()

            # Enqueue evaluation
            await r.lpush(
                "queue:evaluate",
                json.dumps({"run_id": run_id, "query": query, "answer": full_response,
                            "chunk_ids": chunk_ids}),
            )

            yield {"data": json.dumps({"type": "done", "run_id": run_id, "citations": citations})}

        except Exception as exc:
            logger.error("query.stream.error", run_id=run_id, error=str(exc))
            queries_total.labels(pipeline_id=pipeline_id, status="error").inc()
            await pool.execute("UPDATE pipeline_runs SET status='error' WHERE id=$1", run_id)
            yield {"data": json.dumps({"type": "error", "message": str(exc)})}
        finally:
            await r.aclose()

        # Keepalive handled by sse-starlette ping_interval
    return EventSourceResponse(event_generator(), ping=15)
