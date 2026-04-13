from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main app settings declaration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = Field(description="Async DB connection string.")
    APP_TITLE: str = Field(default="DEMO API")
    MAX_PROMPT_LENGTH: int = Field(default=5000, ge=1)
    API_KEY_HEADER_NAME: str = Field(default="X-API-Key")
    CORS_ALLOW_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    LLM_MODE: Literal["mock", "real"] = Field(default="mock")
    LLM_PROVIDER: str = Field(default="openrouter")
    LLM_API_KEY: str | None = Field(default=None)
    LLM_MODEL: str = Field(default="openrouter/free")
    LLM_BASE_URL: str | None = Field(default="https://openrouter.ai/api/v1")
    LLM_TIMEOUT_SECONDS: int = Field(default=60, ge=1)




@lru_cache
def get_settings() -> Settings:
    """Returns app settings instance."""
    return Settings()

