"""Fine-tuning pipeline — extract training pairs, submit jobs, track in MLflow."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from statistics import mean

import mlflow
import structlog

from config import settings
from db.pool import get_pool

logger = structlog.get_logger()

TRAINING_DIR = Path("training_data")
TRAINING_DIR.mkdir(exist_ok=True)

PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),                       # phone
]

SYSTEM_PROMPT = (
    "You are a precise research assistant. "
    "Answer questions using only the provided context. "
    "Cite sources as [Source N]."
)


def _has_pii(text: str) -> bool:
    return any(p.search(text) for p in PII_PATTERNS)


def _validate_pair(pair: dict) -> bool:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    assistant = pair.get("assistant_message", "")
    tokens = len(enc.encode(assistant))
    if not (50 <= tokens <= 2000):
        return False
    if "[Source" not in assistant:
        return False
    if pair.get("faithfulness", 1.0) < 0.8:
        return False
    if _has_pii(pair.get("user_message", "")):
        return False
    return True


async def extract_training_pairs(job_id: str) -> tuple[Path, list[dict]]:
    """Query DB for high-quality pairs and write validated JSONL."""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT tp.id, tp.run_id, tp.user_message, tp.assistant_message,
                  tp.quality_score, tp.system_prompt,
                  e.faithfulness
           FROM training_pairs tp
           JOIN evaluations e ON e.run_id = tp.run_id
           LEFT JOIN pipeline_runs pr ON pr.id = tp.run_id
           WHERE tp.quality_score >= 0.82
             AND tp.included_in_job IS NULL
             AND (pr.id IS NULL OR NOT EXISTS (
                 SELECT 1 FROM evaluations e2
                 WHERE e2.run_id = pr.id AND e2.user_rating <= 2
             ))
           ORDER BY tp.quality_score DESC
           LIMIT 500""",
    )

    valid_pairs = []
    for r in rows:
        pair = dict(r)
        if _validate_pair(pair):
            valid_pairs.append(pair)

    jsonl_path = TRAINING_DIR / f"{job_id}.jsonl"
    with open(jsonl_path, "w") as f:
        for pair in valid_pairs:
            record = {
                "messages": [
                    {"role": "system", "content": pair.get("system_prompt") or SYSTEM_PROMPT},
                    {"role": "user", "content": pair["user_message"]},
                    {"role": "assistant", "content": pair["assistant_message"]},
                ]
            }
            f.write(json.dumps(record) + "\n")

    # Mark as included
    if valid_pairs:
        pair_ids = [p["id"] for p in valid_pairs]
        await pool.execute(
            "UPDATE training_pairs SET included_in_job=$1 WHERE id = ANY($2::uuid[])",
            uuid.UUID(job_id), pair_ids,
        )

    return jsonl_path, valid_pairs


async def submit_finetune_job(base_model: str = "llama-3.1-8b-instant") -> dict:
    """Extract pairs, track in MLflow, submit to Groq (placeholder)."""
    job_id = str(uuid.uuid4())
    pool = get_pool()

    await pool.execute(
        "INSERT INTO finetune_jobs (id, base_model, status) VALUES ($1,$2,'pending')",
        job_id, base_model,
    )

    jsonl_path, pairs = await extract_training_pairs(job_id)

    if not pairs:
        await pool.execute(
            "UPDATE finetune_jobs SET status='failed' WHERE id=$1", job_id
        )
        return {"job_id": job_id, "status": "failed", "reason": "no_valid_pairs"}

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("neuroflow-finetuning")

    with mlflow.start_run(run_name=f"finetune-{job_id[:8]}") as run:
        mlflow.log_params({
            "base_model": base_model,
            "training_pair_count": len(pairs),
            "avg_quality_score": round(mean(p["quality_score"] for p in pairs), 4),
        })
        mlflow.log_artifact(str(jsonl_path))
        mlflow_run_id = run.info.run_id

    await pool.execute(
        """UPDATE finetune_jobs SET status='submitted', training_pair_count=$1,
           mlflow_run_id=$2 WHERE id=$3""",
        len(pairs), mlflow_run_id, job_id,
    )

    # Note: Groq does not yet support fine-tuning API.
    # When available, submit here. For now, mark as submitted for tracking.
    logger.info("finetune.submitted", job_id=job_id, pairs=len(pairs))
    return {
        "job_id": job_id,
        "status": "submitted",
        "training_pair_count": len(pairs),
        "mlflow_run_id": mlflow_run_id,
        "jsonl_path": str(jsonl_path),
    }


async def preview_training_pairs(n: int = 5) -> list[dict]:
    """Show sample pairs without actually submitting a job."""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT tp.user_message, tp.assistant_message, tp.quality_score, e.faithfulness
           FROM training_pairs tp
           JOIN evaluations e ON e.run_id = tp.run_id
           WHERE tp.quality_score >= 0.82 AND tp.included_in_job IS NULL
           ORDER BY tp.quality_score DESC LIMIT $1""",
        n,
    )
    return [dict(r) for r in rows]
