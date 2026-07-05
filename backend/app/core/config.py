"""Server-side configuration for the Evidentia backend.

Secrets are read from backend/.env (via pydantic-settings). They are owned by
the backend and are never returned in API responses or exposed to the frontend.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    evidentia_use_llm: bool = False
    evidentia_llm_provider: str = "openai"
    evidentia_llm_model: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def is_llm_enabled(self) -> bool:
        if not self.evidentia_use_llm:
            return False
        if self.evidentia_llm_provider == "openai":
            return bool(self.openai_api_key)
        if self.evidentia_llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False

    def active_provider(self) -> str:
        return self.evidentia_llm_provider if self.is_llm_enabled() else "none"

    def active_model(self):
        return self.evidentia_llm_model if self.is_llm_enabled() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
