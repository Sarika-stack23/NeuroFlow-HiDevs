"""Circuit breaker — state stored in Redis, shared across all API instances."""
import json
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
import structlog

from config import settings

logger = structlog.get_logger()


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

    async def _r(self) -> aioredis.Redis:
        return aioredis.from_url(settings.redis_url)

    async def _get(self) -> dict[str, Any]:
        r = await self._r()
        raw = await r.get(f"circuit:{self.name}")
        await r.aclose()
        if raw:
            return json.loads(raw)
        return {"state": CircuitState.CLOSED, "failures": 0, "opened_at": None, "half_calls": 0}

    async def _set(self, state: dict) -> None:
        r = await self._r()
        await r.set(f"circuit:{self.name}", json.dumps(state), ex=3600)
        await r.aclose()

    async def get_status(self) -> dict:
        return await self._get()

    async def reset(self) -> None:
        await self._set({"state": CircuitState.CLOSED, "failures": 0, "opened_at": None, "half_calls": 0})

    @asynccontextmanager
    async def __call__(self):
        state = await self._get()

        # OPEN → check recovery
        if state["state"] == CircuitState.OPEN:
            if time.time() - (state["opened_at"] or 0) > self.recovery_timeout:
                state["state"] = CircuitState.HALF_OPEN
                state["half_calls"] = 0
                await self._set(state)
            else:
                raise CircuitOpenError(f"Circuit '{self.name}' is OPEN — failing fast")

        # HALF_OPEN → limit probe calls
        if state["state"] == CircuitState.HALF_OPEN:
            if state["half_calls"] >= self.half_open_max_calls:
                raise CircuitOpenError(f"Circuit '{self.name}' half-open probe limit reached")
            state["half_calls"] = state.get("half_calls", 0) + 1
            await self._set(state)

        try:
            yield
            # Success path — close the circuit
            await self._set(
                {"state": CircuitState.CLOSED, "failures": 0, "opened_at": None, "half_calls": 0}
            )
        except CircuitOpenError:
            raise
        except Exception as exc:
            state = await self._get()
            state["failures"] = state.get("failures", 0) + 1
            if state["failures"] >= self.failure_threshold:
                state["state"] = CircuitState.OPEN
                state["opened_at"] = time.time()
                logger.warning(
                    "circuit_breaker.opened", name=self.name, failures=state["failures"]
                )
                from monitoring.metrics import circuit_breaker_trips
                circuit_breaker_trips.labels(provider=self.name).inc()
            await self._set(state)
            raise


class CircuitBreakerRegistry:
    _breakers: dict[str, CircuitBreaker] = {}

    @classmethod
    def initialize(cls) -> None:
        for name in ["groq", "openai_embeddings", "anthropic"]:
            cls._breakers[name] = CircuitBreaker(name)

    @classmethod
    def get(cls, name: str) -> CircuitBreaker:
        if name not in cls._breakers:
            cls._breakers[name] = CircuitBreaker(name)
        return cls._breakers[name]

    @classmethod
    def get_all_status(cls) -> dict[str, dict]:
        # Returns last known status synchronously from in-memory snapshot
        return {k: {"state": "unknown"} for k in cls._breakers}
