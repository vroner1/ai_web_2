from __future__ import annotations
from app.config import Settings
from app.ml_model.base import BaseLLM
from app.ml_model.ml_model import MockLLM
from app.ml_model.openrouter import OpenRouterLLM


def build_llm(settings: Settings) -> BaseLLM:
    if settings.LLM_MODE == "mock":
        return MockLLM()

    if settings.LLM_MODE == "real":
        if not settings.LLM_API_KEY:
            raise ValueError("LLM_API_KEY is required when LLM_MODE=real")

        if settings.LLM_PROVIDER != "openrouter":
            raise ValueError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")

        return OpenRouterLLM(
            api_key=settings.LLM_API_KEY,
            model_name=settings.LLM_MODEL,
            base_url=settings.LLM_BASE_URL or "https://openrouter.ai/api/v1",
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            app_title=settings.APP_TITLE,
        )

    raise ValueError(f"Unsupported LLM_MODE: {settings.LLM_MODE}")