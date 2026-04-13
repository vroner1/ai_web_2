from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass(slots=True)
class LLMResult:
    text: str
    model_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMStreamEvent:
    token: str = ""
    done: bool = False
    model_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseLLM(ABC):
    provider_name: str
    model_name: str

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[LLMStreamEvent]:
        pass