"""Tests for deployment-related settings plumbing (offline, no network/DB)."""

from app.core.config import Settings, _to_asyncpg_url


def test_auto_tls_and_explicit_local_override(monkeypatch) -> None:
    from app.core.db import engine_kwargs

    for host, mode, expected_tls in [
        ("remote.example", "auto", True),
        ("localhost", "auto", False),
        ("db", "auto", False),
        ("remote.example", "disable", False),
        ("localhost", "require", True),
    ]:
        settings = Settings(_env_file=None, database_url=f"postgresql://u:p@{host}/db", db_ssl=mode)
        monkeypatch.setattr("app.core.db.get_settings", lambda settings=settings: settings)
        options = engine_kwargs()["connect_args"]
        assert (options.get("ssl") == "require") is expected_tls
        assert options["timeout"] > 0


def test_config_file_paths_do_not_depend_on_working_directory(monkeypatch) -> None:
    from pathlib import Path

    paths = Settings.model_config["env_file"]
    assert all(Path(path).is_absolute() for path in paths)
    monkeypatch.chdir(Path(__file__).resolve().parent)
    assert Settings.model_config["env_file"] == paths


def test_normalizer_accepts_neon_style_urls() -> None:
    """Vendor URLs work verbatim: driver added, libpq params stripped."""
    raw = (
        "postgresql://u:p@ep-x.aws.neon.tech/cinemind"
        "?sslmode=require&channel_binding=require"
    )
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
