"""Shared database setup: engine, session factory, FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine_kwargs() -> dict[str, object]:
    """Engine options shared by the app engine and one-off CLI engines.

    ``pool_pre_ping`` + ``pool_recycle`` survive managed-Postgres idle
    disconnects (Neon scales to zero and drops idle TCP); ``connect_args``
    TLS matches the DB_SSL setting.
    """
    settings = get_settings()
    kwargs: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    if settings.db_ssl == "require":
        kwargs["connect_args"] = {"ssl": "require"}
    return kwargs


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, **engine_kwargs())
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, creating it on first use."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a database session (auto-commit/close)."""
    session = get_sessionmaker()
    async with session() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine (used on app shutdown and in tests)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
