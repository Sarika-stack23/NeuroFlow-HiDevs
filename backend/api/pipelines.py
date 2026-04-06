"""Pipeline CRUD, versioning, A/B comparison."""
import asyncio
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import get_current_user, require_scope
from db.pool import get_pool
from models.pipeline import PipelineConfig

router = APIRouter()
logger = structlog.get_logger()


class CreatePipelineBody(BaseModel):
    name: str
    config: dict


class CompareBody(BaseModel):
    query: str
    pipeline_a_id: str
    pipeline_b_id: str


@router.post("/pipelines", tags=["Pipelines"], summary="Create a named pipeline")
async def create_pipeline(body: CreatePipelineBody, _=Depends(require_scope("admin"))):
    # Validate config schema
    try:
        PipelineConfig(**body.config)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    pool = get_pool()
    pipeline_id = str(uuid.uuid4())
    await pool.execute(
        "INSERT INTO pipelines (id, name, config) VALUES ($1, $2, $3)",
        pipeline_id, body.name, json.dumps(body.config),
    )
    return {"pipeline_id": pipeline_id, "name": body.name, "version": 1}


@router.get("/pipelines", tags=["Pipelines"])
async def list_pipelines(_=Depends(get_current_user)):
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT p.id, p.name, p.version, p.created_at,
               COUNT(pr.id) AS run_count,
               AVG(e.overall_score) AS avg_score
           FROM pipelines p
           LEFT JOIN pipeline_runs pr ON pr.pipeline_id = p.id
               AND pr.created_at > NOW() - INTERVAL '7 days'
           LEFT JOIN evaluations e ON e.run_id = pr.id
           WHERE p.status = 'active'
           GROUP BY p.id ORDER BY p.created_at DESC"""
    )
    return [dict(r) for r in rows]


@router.get("/pipelines/{pipeline_id}", tags=["Pipelines"])
async def get_pipeline(pipeline_id: str, _=Depends(get_current_user)):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM pipelines WHERE id = $1", pipeline_id)
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return dict(row)


@router.patch("/pipelines/{pipeline_id}", tags=["Pipelines"])
async def update_pipeline(pipeline_id: str, body: CreatePipelineBody, _=Depends(require_scope("admin"))):
    try:
        PipelineConfig(**body.config)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    pool = get_pool()
    row = await pool.fetchrow("SELECT version, config FROM pipelines WHERE id = $1", pipeline_id)
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Archive old version
    await pool.execute(
        "INSERT INTO pipeline_versions (pipeline_id, version, config) VALUES ($1, $2, $3)",
        pipeline_id, row["version"], row["config"],
    )
    new_version = row["version"] + 1
    await pool.execute(
        "UPDATE pipelines SET config=$1, version=$2 WHERE id=$3",
        json.dumps(body.config), new_version, pipeline_id,
    )
    return {"pipeline_id": pipeline_id, "version": new_version}


@router.delete("/pipelines/{pipeline_id}", tags=["Pipelines"])
async def delete_pipeline(pipeline_id: str, _=Depends(require_scope("admin"))):
    pool = get_pool()
    await pool.execute("UPDATE pipelines SET status='archived' WHERE id=$1", pipeline_id)
    return {"status": "archived"}


@router.get("/pipelines/{pipeline_id}/runs", tags=["Pipelines"])
async def get_pipeline_runs(pipeline_id: str, page: int = 1, page_size: int = 20, _=Depends(get_current_user)):
    pool = get_pool()
    offset = (page - 1) * page_size
    rows = await pool.fetch(
        """SELECT pr.*, e.overall_score, e.faithfulness
           FROM pipeline_runs pr
           LEFT JOIN evaluations e ON e.run_id = pr.id
           WHERE pr.pipeline_id = $1
           ORDER BY pr.created_at DESC LIMIT $2 OFFSET $3""",
        pipeline_id, page_size, offset,
    )
    return [dict(r) for r in rows]


@router.get("/pipelines/{pipeline_id}/analytics", tags=["Pipelines"])
async def get_pipeline_analytics(pipeline_id: str, _=Depends(get_current_user)):
    pool = get_pool()
    latency = await pool.fetchrow(
        """SELECT
               percentile_cont(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99,
               AVG(input_tokens + output_tokens) AS avg_tokens,
               COUNT(*) AS total_runs
           FROM pipeline_runs WHERE pipeline_id = $1 AND status='complete'""",
        pipeline_id,
    )
    scores = await pool.fetchrow(
        """SELECT AVG(e.faithfulness) AS faithfulness,
                  AVG(e.answer_relevance) AS answer_relevance,
                  AVG(e.context_precision) AS context_precision,
                  AVG(e.context_recall) AS context_recall,
                  AVG(e.overall_score) AS overall_score
           FROM evaluations e
           JOIN pipeline_runs pr ON pr.id = e.run_id
           WHERE pr.pipeline_id = $1""",
        pipeline_id,
    )
    return {"latency": dict(latency) if latency else {}, "quality": dict(scores) if scores else {}}


@router.post("/pipelines/compare", tags=["Pipelines"])
async def compare_pipelines(body: CompareBody, _=Depends(get_current_user)):
    """Run the same query through two pipelines simultaneously."""
    from api.query import submit_query
    from pydantic import BaseModel as BM

    class _Q(BM):
        query: str
        pipeline_id: str
        stream: bool = False

    pool = get_pool()

    async def run_pipeline(pid: str):
        import time
        t0 = time.time()
        run_id = str(uuid.uuid4())
        await pool.execute(
            "INSERT INTO pipeline_runs (id, pipeline_id, query, status) VALUES ($1,$2,$3,'running')",
            run_id, pid, body.query,
        )
        # Simplified inline RAG for comparison
        from pipelines.retrieval.retriever import Retriever
        from pipelines.generation.prompt_builder import build_prompt
        from providers.base import RoutingCriteria
        from providers.router import get_router

        retriever = Retriever()
        chunks = await retriever.retrieve(body.query, k=10)
        from pipelines.retrieval.context_assembler import assemble_context
        context, _ = assemble_context(chunks)
        messages = build_prompt(body.query, context, "factual")

        router_inst = get_router()
        provider, model = await router_inst.route(RoutingCriteria())
        result = await provider.complete(messages)

        latency = int((time.time() - t0) * 1000)
        await pool.execute(
            "UPDATE pipeline_runs SET generation=$1, model_used=$2, latency_ms=$3, status='complete' WHERE id=$4",
            result.content, model, latency, run_id,
        )
        return {
            "run_id": run_id,
            "generation": result.content,
            "total_latency_ms": latency,
            "chunks_used": len(chunks),
            "model": model,
        }

    result_a, result_b = await asyncio.gather(
        run_pipeline(body.pipeline_a_id), run_pipeline(body.pipeline_b_id)
    )
    return {"query": body.query, "pipeline_a": result_a, "pipeline_b": result_b}
