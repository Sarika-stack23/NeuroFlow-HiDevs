"""Fine-tuning API — submit jobs, list jobs, preview training data."""
from fastapi import APIRouter, Depends
from api.auth import require_scope, get_current_user
from db.pool import get_pool

router = APIRouter(prefix="/finetune")


@router.post("/jobs", tags=["Fine-Tuning"])
async def submit_job(base_model: str = "llama-3.1-8b-instant", _=Depends(require_scope("admin"))):
    from pipelines.finetuning.pipeline import submit_finetune_job
    return await submit_finetune_job(base_model)


@router.get("/jobs", tags=["Fine-Tuning"])
async def list_jobs(_=Depends(get_current_user)):
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM finetune_jobs ORDER BY created_at DESC")
    return [dict(r) for r in rows]


@router.get("/jobs/{job_id}", tags=["Fine-Tuning"])
async def get_job(job_id: str, _=Depends(get_current_user)):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM finetune_jobs WHERE id=$1", job_id)
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(row)


@router.get("/training-data/preview", tags=["Fine-Tuning"])
async def preview_data(n: int = 5, _=Depends(get_current_user)):
    from pipelines.finetuning.pipeline import preview_training_pairs
    return await preview_training_pairs(n)
