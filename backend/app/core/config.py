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
    # off | summary | full  (default: summary — one LLM call)
    evidentia_llm_intensity: str = "summary"
    evidentia_max_context_chars: int = 6000
    evidentia_max_output_tokens: int = 700
    evidentia_enable_cache: bool = True

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

    def effective_intensity(self) -> str:
        """Resolved intensity: 'off' unless the LLM is enabled and a mode is set."""
        if not self.is_llm_enabled():
            return "off"
        val = (self.evidentia_llm_intensity or "summary").lower()
        if val not in ("off", "summary", "full"):
            val = "summary"
        return val

    def active_provider(self) -> str:
        return self.evidentia_llm_provider if self.effective_intensity() != "off" else "none"

    def active_model(self):
        return self.evidentia_llm_model if self.effective_intensity() != "off" else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
