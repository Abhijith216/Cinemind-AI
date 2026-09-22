"""Application settings, loaded from environment variables.

All settings are prefixed with ``CINEMIND_``. Secrets are never hardcoded:
copy ``.env.example`` to ``.env`` and fill in real values (backend loads
``.env`` from the *repo root* and from ``backend/``).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings (see .env.example for documentation)."""

    model_config = SettingsConfigDict(
        env_prefix="CINEMIND_",
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind"

    # --- TMDb ---
    tmdb_api_key: str = ""

    # --- LLM (OpenAI-compatible chat completions) ---
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # --- Embeddings ---
    embedding_provider: str = "openai"  # "openai" | "local"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
