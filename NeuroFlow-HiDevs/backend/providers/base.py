"""Abstract base class for LLM providers."""
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str | list  # str for text, list for multi-modal


@dataclass
class GenerationResult:
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    finish_reason: str


@dataclass
class RoutingCriteria:
    task_type: str = "rag_generation"  # rag_generation | evaluation | embedding | classification
    max_cost_per_call: float | None = None
    require_vision: bool = False
    require_long_context: bool = False  # > 32k tokens
    latency_budget_ms: int | None = None
    prefer_fine_tuned: bool = False


class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[ChatMessage], **kwargs) -> GenerationResult: ...

    @abstractmethod
    async def stream(
        self, messages: list[ChatMessage], **kwargs
    ) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def cost_per_input_token(self) -> float: ...

    @property
    @abstractmethod
    def cost_per_output_token(self) -> float: ...

    @property
    @abstractmethod
    def context_window(self) -> int: ...
