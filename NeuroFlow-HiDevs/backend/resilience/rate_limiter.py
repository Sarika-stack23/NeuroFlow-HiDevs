"""Token-bucket rate limiter stored in Redis."""
import time

import redis.asyncio as aioredis
import structlog
from fastapi import HTTPException, Request

from config import settings

logger = structlog.get_logger()


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url)


async def token_bucket_check(key: str, capacity: int, refill_rate: float) -> bool:
    """
    Returns True if request is allowed, False if rate-limited.
    capacity: max tokens in bucket
    refill_rate: tokens added per second
    """
    r = await _get_redis()
    now = time.time()
    bucket_key = f"rpb:{key}"

    pipe = r.pipeline()
    pipe.hgetall(bucket_key)
    results = await pipe.execute()
    data = results[0]

    if data:
        tokens = float(data.get(b"tokens", capacity))
        last_refill = float(data.get(b"last_refill", now))
        elapsed = now - last_refill
        tokens = min(capacity, tokens + elapsed * refill_rate)
    else:
        tokens = float(capacity)
        last_refill = now

    allowed = tokens >= 1.0
    if allowed:
        tokens -= 1.0

    await r.hset(bucket_key, mapping={"tokens": tokens, "last_refill": now})
    await r.expire(bucket_key, 3600)
    await r.aclose()
    return allowed


async def sliding_window_check(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Sliding window counter. Returns (allowed, retry_after_seconds)."""
    r = await _get_redis()
    now = time.time()
    window_key = f"sw:{key}:{int(now // window_seconds)}"

    count = await r.incr(window_key)
    await r.expire(window_key, window_seconds * 2)
    await r.aclose()

    allowed = count <= limit
    retry_after = window_seconds - int(now % window_seconds) if not allowed else 0
    return allowed, retry_after


def rate_limit(limit: int, window_seconds: int, key_prefix: str = "api"):
    """FastAPI dependency for endpoint rate limiting."""
    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{key_prefix}:{client_ip}"
        allowed, retry_after = await sliding_window_check(key, limit, window_seconds)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
    return dependency
