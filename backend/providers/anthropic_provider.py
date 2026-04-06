"""Anthropic Claude provider."""
import time
from typing import AsyncGenerator

import anthropic

from providers.base import BaseLLMProvider, ChatMessage, GenerationResult

PRICE_TABLE = {
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
}


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    prices = PRICE_TABLE.get(model, {"input": 3.0, "output": 15.0})
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


class AnthropicProvider(BaseLLMProvider):
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    @property
    def cost_per_input_token(self) -> float:
        return PRICE_TABLE.get(self._model, {}).get("input", 3.0) / 1_000_000

    @property
    def cost_per_output_token(self) -> float:
        return PRICE_TABLE.get(self._model, {}).get("output", 15.0) / 1_000_000

    @property
    def context_window(self) -> int:
        return 200000  # All Claude 3 models

    def _split_messages(self, messages: list[ChatMessage]):
        system = next((m.content for m in messages if m.role == "system"), None)
        convo = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        return system, convo

    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult:
        system, convo = self._split_messages(messages)
        t0 = time.time()
        resp = await self._client.messages.create(
            model=kwargs.get("model", self._model),
            max_tokens=kwargs.get("max_tokens", 1000),
            system=system or "",
            messages=convo,
        )
        latency_ms = (time.time() - t0) * 1000
        content = resp.content[0].text if resp.content else ""
        return GenerationResult(
            content=content,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd=_calc_cost(resp.model, resp.usage.input_tokens, resp.usage.output_tokens),
            finish_reason=resp.stop_reason or "stop",
        )

    async def stream(self, messages: list[ChatMessage], **kwargs) -> AsyncGenerator[str, None]:
        system, convo = self._split_messages(messages)
        async with self._client.messages.stream(
            model=kwargs.get("model", self._model),
            max_tokens=kwargs.get("max_tokens", 1000),
            system=system or "",
            messages=convo,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("Anthropic does not provide an embeddings API")
