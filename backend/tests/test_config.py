"""Tests for deployment-related settings plumbing (offline, no network/DB)."""

from app.core.config import Settings, _to_asyncpg_url


def test_normalizer_accepts_neon_style_urls() -> None:
    """Vendor URLs work verbatim: driver added, sslmode stripped."""
    raw = "postgresql://u:p@ep-x.aws.neon.tech/cinemind?sslmode=require"
    assert _to_asyncpg_url(raw) == "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/cinemind"
    assert _to_asyncpg_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_normalizer_preserves_other_query_params() -> None:
    url = _to_asyncpg_url("postgresql://u:p@h/db?sslmode=require&application_name=x")
    assert url == "postgresql+asyncpg://u:p@h/db?application_name=x"


def test_normalizer_leaves_asyncpg_urls_alone() -> None:
    url = "postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind"
    assert _to_asyncpg_url(url) == url


def test_settings_normalize_database_urls() -> None:
    settings = Settings(database_url="postgresql://u:p@h/db?sslmode=require")
    assert settings.database_url == "postgresql+asyncpg://u:p@h/db"
    # migrations_url falls back to the app URL when no direct URL is set
    assert settings.migrations_url == settings.database_url


def test_migrations_url_prefers_direct() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@pooled/db",
        database_url_direct="postgresql://u:p@direct/db",
    )
    assert settings.migrations_url == "postgresql+asyncpg://u:p@direct/db"
