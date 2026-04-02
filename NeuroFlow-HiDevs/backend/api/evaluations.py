"""Evaluations API — list, aggregate, SSE feed, user rating."""
import asyncio
import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from api.auth import get_current_user
from config import settings
from db.pool import get_pool

router = APIRouter()
logger = structlog.get_logger()


@router.get("/evaluations", tags=["Evaluation"])
async def list_evaluations(
    page: int = 1,
    page_size: int = 20,
    pipeline_id: str | None = None,
    min_score: float | None = None,
    _=Depends(get_current_user),
):
    pool = get_pool()
    conditions = ["1=1"]
    params: list = []

    if pipeline_id:
        params.append(pipeline_id)
        conditions.append(f"pr.pipeline_id = ${len(params)}")
    if min_score is not None:
        params.append(min_score)
        conditions.append(f"e.overall_score >= ${len(params)}")

    where = " AND ".join(conditions)
    params += [page_size, (page - 1) * page_size]

    rows = await pool.fetch(
        f"""SELECT e.*, pr.query, pr.pipeline_id, pr.model_used
            FROM evaluations e
            JOIN pipeline_runs pr ON pr.id = e.run_id
            WHERE {where}
            ORDER BY e.evaluated_at DESC
            LIMIT ${len(params) - 1} OFFSET ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


@router.get("/evaluations/aggregate", tags=["Evaluation"])
async def get_aggregate(_=Depends(get_current_user)):
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT pr.pipeline_id,
               AVG(e.faithfulness) AS faithfulness,
               AVG(e.answer_relevance) AS answer_relevance,
               AVG(e.context_precision) AS context_precision,
               AVG(e.context_recall) AS context_recall,
               AVG(e.overall_score) AS overall_score,
               COUNT(*) AS eval_count
           FROM evaluations e
           JOIN pipeline_runs pr ON pr.id = e.run_id
           WHERE e.evaluated_at > NOW() - INTERVAL '24 hours'
           GROUP BY pr.pipeline_id"""
    )
    return [dict(r) for r in rows]


class RatingBody(BaseModel):
    rating: int  # 1-5


@router.patch("/runs/{run_id}/rating", tags=["Evaluation"])
async def patch_rating(run_id: str, body: RatingBody, _=Depends(get_current_user)):
    if not 1 <= body.rating <= 5:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Rating must be 1-5")

    pool = get_pool()
    await pool.execute(
        "UPDATE evaluations SET user_rating=$1 WHERE run_id=$2",
        body.rating, run_id,
    )
    # Check for calibration drift
    row = await pool.fetchrow(
        "SELECT overall_score, user_rating FROM evaluations WHERE run_id=$1", run_id
    )
    if row and row["overall_score"] is not None and row["user_rating"] is not None:
        drift = abs(row["overall_score"] - row["user_rating"] / 5.0)
        if drift > 0.3:
            await pool.execute(
                """UPDATE evaluations SET metadata = metadata || '{"calibration_needed": true}'
                   WHERE run_id=$1""",
                run_id,
            )
    return {"status": "ok"}


@router.get("/evaluations/stream", tags=["Evaluation"])
async def stream_evaluations(_=Depends(get_current_user)):
    """SSE stream — emits new evaluation events in real-time."""

    async def generator():
        r = aioredis.from_url(settings.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe("evaluations:new")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield {"data": message["data"].decode()}
                    await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe("evaluations:new")
            await r.aclose()

    return EventSourceResponse(generator(), ping=20)
