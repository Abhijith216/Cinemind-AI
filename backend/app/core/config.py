"""Application settings, loaded from environment variables.

Plain environment names (``DATABASE_URL``, ``OPENAI_API_KEY``,
``TMDB_API_KEY``, ``JWT_SECRET``, ...). Secrets are never hardcoded:
copy ``backend/.env.example`` to ``backend/.env`` and fill in real values.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_asyncpg_url(url: str) -> str:
    """Normalize a Postgres URL to the asyncpg driver form.

    Neon/Supabase/Render hand out ``postgresql://user:pass@host/db`` (and
    may append ``?sslmode=require``). asyncpg needs the ``+asyncpg`` driver
    and rejects ``sslmode`` as a query param — strip it (DB_SSL governs TLS).
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode=" in url:
        base, _, query = url.partition("?")
        kept = "&".join(
            part for part in query.split("&") if not part.startswith("sslmode=")
        )
        url = f"{base}?{kept}" if kept else base
    return url


class Settings(BaseSettings):
    """Typed application settings (see backend/.env.example for documentation)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = "postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind"
    # Optional separate URL for one-off admin work (migrations, ingest CLI,
    # embedding backfill). Falls back to ``database_url`` when empty.
    # Neon/Supabase pooled URLs can reject migration DDL — point this at the
    # direct (unpooled) connection string in production.
    database_url_direct: str = ""
    # TLS for the app's async connections. "require" matches Neon/Supabase and
    # most managed Postgres; "disable" for local docker-compose Postgres.
    db_ssl: str = "disable"

    @field_validator("database_url", "database_url_direct")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        """Accept vendor URLs verbatim (driver + sslmode handled here)."""
        return _to_asyncpg_url(value) if value else value

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

    # --- Observability ---
    # "human" (readable) or "json" (one JSON object per stdout line — use in
    # production so Render's log stream stays queryable).
    log_format: str = "human"
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def migrations_url(self) -> str:
        """URL used by Alembic and the one-time data CLIs.

        Prefers the explicit direct URL, falling back to the app URL.
        """
        return self.database_url_direct or self.database_url


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
