from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.ml_model.base import BaseLLM, LLMResult, LLMStreamEvent


class LLMProviderError(Exception):
    def __init__(
        self,
        status_code: int,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class OpenRouterLLM(BaseLLM):
    provider_name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: int = 60,
        app_title: str = "DEMO API",
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.app_title = app_title

    @staticmethod
    def _to_provider_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        provider_messages: list[dict[str, str]] = []
        for msg in messages:
            provider_messages.append(
                {
                    "role": msg["role"],
                    "content": msg["message"],
                }
            )
        return provider_messages

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.app_title,
        }

    def _payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": self._to_provider_messages(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def generate(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> LLMResult:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(messages, temperature, max_tokens, stream=False),
            )

        if response.status_code >= 400:
            payload = {}
            try:
                payload = response.json()
            except Exception:
                pass
            message = payload.get("error", {}).get("message") or response.text
            raise LLMProviderError(response.status_code, message, payload)

        data = response.json()
        text = data["choices"][0]["message"]["content"]

        return LLMResult(
            text=text,
            model_name=data.get("model", self.model_name),
            metadata={
                "provider": self.provider_name,
                "id": data.get("id"),
                "usage": data.get("usage"),
            },
        )

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[LLMStreamEvent]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=self._payload(messages, temperature, max_tokens, stream=True),
            ) as response:
                if response.status_code >= 400:
                    payload = {}
                    try:
                        payload = await response.json()
                    except Exception:
                        pass
                    body = await response.aread()
                    message = payload.get("error", {}).get("message") or body.decode(
                        "utf-8", errors="ignore"
                    )
                    raise LLMProviderError(response.status_code, message, payload)

                final_model_name: str | None = None
                final_usage: dict[str, Any] = {}

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break

                    chunk = json.loads(data_str)

                    if "error" in chunk:
                        error = chunk["error"]
                        raise LLMProviderError(
                            response.status_code,
                            error.get("message", "Streaming provider error"),
                            chunk,
                        )

                    final_model_name = chunk.get("model", final_model_name)
                    if chunk.get("usage"):
                        final_usage = chunk["usage"]

                    delta = ""
                    choices = chunk.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta", {}).get("content", "") or ""

                    if delta:
                        yield LLMStreamEvent(token=delta)

                yield LLMStreamEvent(
                    done=True,
                    model_name=final_model_name or self.model_name,
                    metadata={
                        "provider": self.provider_name,
                        "usage": final_usage,
                    },
                )