"""Shared database setup: engine, session factory, FastAPI dependency."""

import asyncio
from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
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
        "pool_recycle": 60,
        "pool_timeout": 5,
    }
    connect_args: dict[str, object] = {"timeout": 15, "command_timeout": 15}
    remote_database = make_url(settings.database_url).host not in {
        None,
        "localhost",
        "127.0.0.1",
        "::1",
        "db",
    }
    if settings.db_ssl == "require" or (settings.db_ssl == "auto" and remote_database):
        connect_args["ssl"] = "require"
    kwargs["connect_args"] = connect_args
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
    db = get_sessionmaker()()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


async def ensure_database_connection(db: AsyncSession) -> None:
    """Recover before the first query, after request validation, without replaying writes."""
    for attempt in range(2):
        try:
            async with asyncio.timeout(10):
                await db.connection()
            return
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            await db.rollback()
            await get_engine().dispose()
            if attempt:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "The movie catalog is temporarily unavailable. Please try again shortly."
                    ),
                ) from exc


async def dispose_engine() -> None:
    """Dispose the engine (used on app shutdown and in tests)."""
    global _engine, _sessionmaker
    engine = _engine
    _engine = None
    _sessionmaker = None
    if engine is not None:
        await engine.dispose()
