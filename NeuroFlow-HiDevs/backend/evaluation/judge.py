"""LLM-as-Judge — runs all four metrics in parallel and writes to evaluations table."""
from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from opentelemetry import trace

from db.pool import get_pool
from evaluation.metrics import (
    evaluate_answer_relevance,
    evaluate_context_precision,
    evaluate_context_recall,
    evaluate_faithfulness,
)

logger = structlog.get_logger()
tracer = trace.get_tracer("neuroflow.evaluation")

WEIGHTS = {
    "faithfulness": 0.35,
    "answer_relevance": 0.30,
    "context_precision": 0.20,
    "context_recall": 0.15,
}


class EvaluationJudge:
    async def evaluate(
        self,
        run_id: str,
        query: str,
        answer: str,
        context: str,
        chunks: list[str],
        judge_model: str = "llama-3.3-70b-versatile",
    ) -> dict:
        with tracer.start_as_current_span("evaluation.judge") as span:
            span.set_attribute("run_id", run_id)

            # Run all metrics in parallel
            faithfulness, relevance, precision, recall = await asyncio.gather(
                evaluate_faithfulness(query, answer, context),
                evaluate_answer_relevance(query, answer),
                evaluate_context_precision(query, chunks, answer),
                evaluate_context_recall(query, chunks, answer),
            )

            overall = (
                WEIGHTS["faithfulness"] * faithfulness
                + WEIGHTS["answer_relevance"] * relevance
                + WEIGHTS["context_precision"] * precision
                + WEIGHTS["context_recall"] * recall
            )

            span.set_attribute("faithfulness", faithfulness)
            span.set_attribute("answer_relevance", relevance)
            span.set_attribute("context_precision", precision)
            span.set_attribute("context_recall", recall)
            span.set_attribute("overall_score", overall)

            pool = get_pool()
            eval_id = str(uuid.uuid4())
            await pool.execute(
                """INSERT INTO evaluations
                   (id, run_id, faithfulness, answer_relevance, context_precision,
                    context_recall, overall_score, judge_model)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                eval_id, run_id, faithfulness, relevance, precision, recall, overall, judge_model,
            )

            # Extract as training pair if quality is high enough
            if overall >= 0.82 and faithfulness >= 0.8:
                await self._create_training_pair(run_id, query, answer, overall, pool)

            # Publish to Redis for live eval feed
            import redis.asyncio as aioredis
            from config import settings
            r = aioredis.from_url(settings.redis_url)
            await r.publish("evaluations:new", json.dumps({
                "eval_id": eval_id,
                "run_id": run_id,
                "faithfulness": faithfulness,
                "answer_relevance": relevance,
                "context_precision": precision,
                "context_recall": recall,
                "overall_score": overall,
            }))
            await r.aclose()

            logger.info(
                "evaluation.complete",
                run_id=run_id, overall=round(overall, 3),
                faithfulness=round(faithfulness, 3),
            )
            return {
                "eval_id": eval_id,
                "faithfulness": faithfulness,
                "answer_relevance": relevance,
                "context_precision": precision,
                "context_recall": recall,
                "overall_score": overall,
            }

    async def _create_training_pair(
        self, run_id: str, query: str, answer: str, score: float, pool
    ) -> None:
        system_prompt = (
            "You are a precise research assistant. Answer questions using only the provided context."
        )
        await pool.execute(
            """INSERT INTO training_pairs
               (id, run_id, system_prompt, user_message, assistant_message, quality_score)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT DO NOTHING""",
            str(uuid.uuid4()), run_id, system_prompt, query, answer, score,
        )


# ── Background evaluation worker ─────────────────────────────────────────────

async def run_eval_worker() -> None:
    import redis.asyncio as aioredis
    from config import settings

    await asyncio.sleep(2)  # wait for DB pool
    from db.pool import create_pool
    await create_pool()

    r = aioredis.from_url(settings.redis_url)
    judge = EvaluationJudge()
    logger.info("eval_worker.started")

    while True:
        try:
            item = await r.brpop("queue:evaluate", timeout=5)
            if item:
                _, raw = item
                job = json.loads(raw)
                run_id = job["run_id"]
                query = job["query"]
                answer = job["answer"]
                chunk_ids = job.get("chunk_ids", [])

                pool = get_pool()
                # Fetch chunk contents
                chunks: list[str] = []
                if chunk_ids:
                    rows = await pool.fetch(
                        "SELECT content FROM chunks WHERE id = ANY($1::uuid[])",
                        chunk_ids,
                    )
                    chunks = [r["content"] for r in rows]

                context = "\n\n".join(chunks[:8])
                await judge.evaluate(run_id, query, answer, context, chunks)
        except Exception as exc:
            logger.error("eval_worker.error", error=str(exc))
            await asyncio.sleep(2)
