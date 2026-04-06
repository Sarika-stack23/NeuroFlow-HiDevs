"""Unit tests for circuit breaker state machine logic."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeRedis:
    """In-memory fake Redis for testing."""
    def __init__(self):
        self.store: dict = {}

    async def get(self, key):
        val = self.store.get(key)
        return val.encode() if isinstance(val, str) else val

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def cb(fake_redis):
    from resilience.circuit_breaker import CircuitBreaker
    breaker = CircuitBreaker("test", failure_threshold=3, recovery_timeout=60, half_open_max_calls=2)
    # Patch the Redis connection
    with patch.object(breaker, "_r", return_value=fake_redis):
        yield breaker


@pytest.mark.asyncio
async def test_circuit_starts_closed(cb, fake_redis):
    state = await cb._get()
    assert state["state"] == "closed"


@pytest.mark.asyncio
async def test_circuit_opens_after_threshold(cb, fake_redis):
    with patch.object(cb, "_r", return_value=fake_redis):
        for _ in range(3):
            try:
                async with cb():
                    raise RuntimeError("simulated failure")
            except (RuntimeError, Exception):
                pass

    state = await cb._get()
    assert state["state"] == "open"


@pytest.mark.asyncio
async def test_circuit_open_fails_fast(cb, fake_redis):
    # Manually set to open
    await cb._set({"state": "open", "failures": 3, "opened_at": time.time(), "half_calls": 0})
    from resilience.circuit_breaker import CircuitOpenError
    with pytest.raises(CircuitOpenError):
        async with cb():
            pass


@pytest.mark.asyncio
async def test_circuit_half_open_after_timeout(cb, fake_redis):
    # Set opened_at in the past so recovery_timeout is exceeded
    await cb._set({
        "state": "open", "failures": 3,
        "opened_at": time.time() - 120,  # 120s ago > 60s timeout
        "half_calls": 0,
    })
    # Should transition to half_open on next call attempt
    try:
        async with cb():
            pass  # success
    except Exception:
        pass
    state = await cb._get()
    # After a success in half-open → closed
    assert state["state"] in ("closed", "half_open")


@pytest.mark.asyncio
async def test_circuit_reset(cb, fake_redis):
    await cb._set({"state": "open", "failures": 5, "opened_at": time.time(), "half_calls": 0})
    await cb.reset()
    state = await cb._get()
    assert state["state"] == "closed"
    assert state["failures"] == 0


@pytest.mark.asyncio
async def test_circuit_success_clears_failures(cb, fake_redis):
    # Set some failures but not enough to open
    await cb._set({"state": "closed", "failures": 2, "opened_at": None, "half_calls": 0})
    async with cb():
        pass  # success
    state = await cb._get()
    assert state["failures"] == 0
