"""Application settings, loaded from environment variables.

Plain environment names (``DATABASE_URL``, ``OPENAI_API_KEY``,
``TMDB_API_KEY``, ``JWT_SECRET``, ...). Secrets are never hardcoded:
copy ``backend/.env.example`` to ``backend/.env`` and fill in real values.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings (see backend/.env.example for documentation)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind"

    # --- Auth ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # one week

    # --- TMDb ---
    tmdb_api_key: str = ""

    # --- OpenAI (LLM + embeddings; OpenAI-compatible base URL for local models) ---
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # --- Rate limiting (per client per minute; 0 disables — set 0 for local
    # demo/offline use, a real number whenever an API budget is at stake) ---
    chat_rate_limit_per_minute: int = 10
    search_rate_limit_per_minute: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
