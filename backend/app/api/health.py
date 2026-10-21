"""Health endpoint and app metadata."""

import asyncio
import datetime
import logging
import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app import __version__
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.schemas.common import HealthOut, IntegrationStatus

router = APIRouter(tags=["health"])

logger = logging.getLogger("cinemind.health")
_STARTED_AT = time.time()


@router.get("/ready", response_model=HealthOut)
async def readiness(response: Response) -> HealthOut:
    try:
        async with asyncio.timeout(3):
            async with get_sessionmaker()() as db:
                await db.execute(text("SELECT search_document FROM movies LIMIT 0"))
                if get_settings().rate_limit_backend == "database":
                    await db.execute(text("SELECT key FROM rate_limit_buckets LIMIT 0"))
        database = "up"
    except Exception:
        database = "down"
        response.status_code = 503
    return HealthOut(
        status="ok" if database == "up" else "unavailable",
        version=__version__,
        database=database,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
    )


@router.get("/integrations", response_model=IntegrationStatus)
async def integrations() -> IntegrationStatus:
    settings = get_settings()
    return IntegrationStatus(
        chat_configured=bool(
            settings.openai_api_key and settings.openai_base_url and settings.llm_model
        ),
        tmdb_configured=bool(settings.tmdb_api_key),
    )


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness + database reachability probe (200 even if the DB is down)."""
    database = "up"
    database_error: str | None = None
    try:
        session = get_sessionmaker()
        async with session() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health must never 500
        database = "down"
        # Driver messages may contain private connection details.
        database_error = type(exc).__name__
        logger.warning("health: database probe failed: %s", database_error)
    return HealthOut(
        status="ok",
        version=__version__,
        database=database,
        database_error=database_error,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
    )
