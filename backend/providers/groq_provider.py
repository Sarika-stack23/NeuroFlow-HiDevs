"""Groq LLM provider — ultra-fast inference via Groq API (OpenAI-compatible)."""
import asyncio
import time
from typing import AsyncGenerator

import structlog
from openai import AsyncOpenAI, RateLimitError  # Groq uses OpenAI-compatible SDK

from providers.base import BaseLLMProvider, ChatMessage, GenerationResult

logger = structlog.get_logger()

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Prices in USD per million tokens (as of 2025)
PRICE_TABLE: dict[str, dict[str, float]] = {
    "llama-3.3-70b-versatile":   {"input": 0.59,  "output": 0.79},
    "llama-3.1-8b-instant":      {"input": 0.05,  "output": 0.08},
    "llama3-70b-8192":           {"input": 0.59,  "output": 0.79},
    "llama3-8b-8192":            {"input": 0.05,  "output": 0.08},
    "mixtral-8x7b-32768":        {"input": 0.24,  "output": 0.24},
    "gemma2-9b-it":              {"input": 0.20,  "output": 0.20},
    "llama-3.2-11b-vision-preview": {"input": 0.18, "output": 0.18},  # vision
    "llama-3.2-90b-vision-preview": {"input": 0.90, "output": 0.90},  # vision
}

CONTEXT_WINDOWS: dict[str, int] = {
    "llama-3.3-70b-versatile":      128000,
    "llama-3.1-8b-instant":         128000,
    "llama3-70b-8192":              8192,
    "llama3-8b-8192":               8192,
    "mixtral-8x7b-32768":           32768,
    "gemma2-9b-it":                 8192,
    "llama-3.2-11b-vision-preview": 128000,
    "llama-3.2-90b-vision-preview": 128000,
}


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = PRICE_TABLE.get(model, {"input": 0.59, "output": 0.79})
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


class GroqProvider(BaseLLMProvider):
    """
    Groq provider using the OpenAI-compatible client pointed at api.groq.com.
    Supports chat completions, streaming, and embedding (via OpenAI fallback).
    """

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
        )
        self._model = model

    @property
    def cost_per_input_token(self) -> float:
        return PRICE_TABLE.get(self._model, {}).get("input", 0.59) / 1_000_000

    @property
    def cost_per_output_token(self) -> float:
        return PRICE_TABLE.get(self._model, {}).get("output", 0.79) / 1_000_000

    @property
    def context_window(self) -> int:
        return CONTEXT_WINDOWS.get(self._model, 8192)

    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        groq_messages = [{"role": m.role, "content": m.content} for m in messages]
        t0 = time.time()
        for attempt in range(3):
            try:
                resp = await self._client.chat.completions.create(
                    model=kwargs.get("model", self._model),
                    messages=groq_messages,
                    temperature=kwargs.get("temperature", 0.3),
                    max_tokens=kwargs.get("max_tokens", 1024),
                )
                latency_ms = (time.time() - t0) * 1000
                usage = resp.usage
                return GenerationResult(
                    content=resp.choices[0].message.content or "",
                    model=resp.model,
                    input_tokens=usage.prompt_tokens if usage else 0,
                    output_tokens=usage.completion_tokens if usage else 0,
                    latency_ms=latency_ms,
                    cost_usd=_calc_cost(
                        resp.model,
                        usage.prompt_tokens if usage else 0,
                        usage.completion_tokens if usage else 0,
                    ),
                    finish_reason=resp.choices[0].finish_reason or "stop",
                )
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("groq.rate_limit", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        raise RuntimeError("Groq rate limit exceeded after 3 retries")

    async def stream(
        self, messages: list[ChatMessage], **kwargs
    ) -> AsyncGenerator[str, None]:
        groq_messages = [{"role": m.role, "content": m.content} for m in messages]
        stream = await self._client.chat.completions.create(
            model=kwargs.get("model", self._model),
            messages=groq_messages,
            stream=True,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Groq does not provide an embeddings endpoint.
        Falls back to OpenAI text-embedding-3-small.
        The embed API key must be set separately via OPENAI_API_KEY for embeddings.
        """
        from config import settings
        from openai import AsyncOpenAI as OAI

        oai = OAI(api_key=settings.openai_api_key)
        all_embeddings: list[list[float]] = []
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await oai.embeddings.create(
                model="text-embedding-3-small",
                input=batch,
            )
            all_embeddings.extend([e.embedding for e in resp.data])
        return all_embeddings
