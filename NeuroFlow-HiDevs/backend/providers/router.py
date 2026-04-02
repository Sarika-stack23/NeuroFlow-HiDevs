"""Model router — Groq as primary provider, OpenAI embeddings, Anthropic optional fallback."""
import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from config import settings
from providers.base import BaseLLMProvider, RoutingCriteria
from providers.groq_provider import GroqProvider
from providers.anthropic_provider import AnthropicProvider

logger = structlog.get_logger()

DEFAULT_MODELS: list[dict[str, Any]] = [
    {
        "name": "llama-3.1-8b-instant",
        "provider": "groq",
        "task_types": ["rag_generation", "classification"],
        "vision": False,
        "long_context": True,
        "cost_tier": "low",
        "context_window": 128000,
        "est_cost_per_call": 0.001,
    },
    {
        "name": "llama-3.3-70b-versatile",
        "provider": "groq",
        "task_types": ["rag_generation", "evaluation", "classification"],
        "vision": False,
        "long_context": True,
        "cost_tier": "medium",
        "context_window": 128000,
        "est_cost_per_call": 0.01,
    },
    {
        "name": "llama-3.2-11b-vision-preview",
        "provider": "groq",
        "task_types": ["rag_generation", "image_description"],
        "vision": True,
        "long_context": True,
        "cost_tier": "low",
        "context_window": 128000,
        "est_cost_per_call": 0.005,
    },
    {
        "name": "llama-3.2-90b-vision-preview",
        "provider": "groq",
        "task_types": ["evaluation", "image_description"],
        "vision": True,
        "long_context": True,
        "cost_tier": "high",
        "context_window": 128000,
        "est_cost_per_call": 0.05,
    },
    {
        "name": "mixtral-8x7b-32768",
        "provider": "groq",
        "task_types": ["rag_generation", "evaluation"],
        "vision": False,
        "long_context": False,
        "cost_tier": "low",
        "context_window": 32768,
        "est_cost_per_call": 0.005,
    },
    {
        "name": "claude-3-haiku-20240307",
        "provider": "anthropic",
        "task_types": ["rag_generation", "evaluation"],
        "vision": False,
        "long_context": True,
        "cost_tier": "low",
        "context_window": 200000,
        "est_cost_per_call": 0.003,
    },
]


class ModelRouter:
    def __init__(self) -> None:
        self._providers: dict[str, BaseLLMProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        for model_name in [
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
            "llama-3.2-11b-vision-preview",
            "llama-3.2-90b-vision-preview",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]:
            self._providers[f"groq_{model_name}"] = GroqProvider(
                api_key=settings.groq_api_key, model=model_name
            )
        if settings.anthropic_api_key:
            self._providers["anthropic_claude-3-haiku-20240307"] = AnthropicProvider(
                api_key=settings.anthropic_api_key
            )

    async def _get_models(self) -> list[dict[str, Any]]:
        try:
            r = aioredis.from_url(settings.redis_url)
            raw = await r.get("router:models")
            await r.aclose()
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return DEFAULT_MODELS

    async def route(self, criteria: RoutingCriteria) -> tuple[BaseLLMProvider, str]:
        models = await self._get_models()
        candidates = list(models)

        if criteria.require_vision:
            candidates = [m for m in candidates if m.get("vision")]
        if criteria.require_long_context:
            candidates = [m for m in candidates if m.get("context_window", 0) > 32000]
        if criteria.task_type == "evaluation":
            candidates = [m for m in candidates if not m.get("fine_tuned")]
            preferred = [m for m in candidates if m.get("cost_tier") in ("medium", "high")]
            if preferred:
                candidates = preferred
        if criteria.max_cost_per_call is not None:
            under = [m for m in candidates if m.get("est_cost_per_call", 999) <= criteria.max_cost_per_call]
            if under:
                candidates = under
        if criteria.prefer_fine_tuned:
            ft = [m for m in candidates if m.get("fine_tuned") and criteria.task_type in m.get("task_types", [])]
            if ft:
                candidates = ft

        if not candidates:
            candidates = models

        task_match = [m for m in candidates if criteria.task_type in m.get("task_types", [])]
        pool = task_match if task_match else candidates
        best = sorted(pool, key=lambda m: m.get("est_cost_per_call", 999))[0]

        key = f"{best['provider']}_{best['name']}"
        provider = self._providers.get(key) or self._providers.get("groq_llama-3.1-8b-instant") or list(self._providers.values())[0]

        logger.info("router.selected", model=best["name"], task_type=criteria.task_type)
        return provider, best["name"]


_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
