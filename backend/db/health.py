"""Health check functions for each service."""
import httpx
import redis.asyncio as aioredis
from config import settings
from db.pool import get_pool


async def check_postgres() -> bool:
    try:
        pool = get_pool()
        await pool.fetchval("SELECT 1")
        return True
    except Exception:
        return False


async def check_redis() -> bool:
    try:
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def check_mlflow() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.mlflow_tracking_uri}/health")
            return resp.status_code == 200
    except Exception:
        return False
