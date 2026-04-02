"""Admin API — circuit breaker reset, system controls."""
from fastapi import APIRouter, Depends
from api.auth import require_scope

router = APIRouter()


@router.post("/circuit-breaker/reset", tags=["Admin"])
async def reset_circuit_breaker(name: str, _=Depends(require_scope("admin"))):
    from resilience.circuit_breaker import CircuitBreakerRegistry
    cb = CircuitBreakerRegistry.get(name)
    await cb.reset()
    return {"status": "reset", "name": name}


@router.get("/queue/stats", tags=["Admin"])
async def queue_stats(_=Depends(require_scope("admin"))):
    import redis.asyncio as aioredis
    from config import settings
    r = aioredis.from_url(settings.redis_url)
    ingest_depth = await r.llen(settings.ingest_queue_key)
    eval_depth = await r.llen("queue:evaluate")
    await r.aclose()
    return {"ingest_queue": ingest_depth, "eval_queue": eval_depth}
