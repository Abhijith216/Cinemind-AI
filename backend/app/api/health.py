"""Health endpoint and app metadata."""

import datetime
import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.core.db import get_sessionmaker
from app.schemas.common import HealthOut

router = APIRouter(tags=["health"])

logger = logging.getLogger("cinemind.health")
_STARTED_AT = time.time()


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
        # Root cause is actionable (wrong URL, TLS, network); the traceback
        # would bloat the payload, so surface type + first line only.
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        database_error = f"{type(exc).__name__}: {first_line[:200]}"
        logger.warning(
            "health: database probe failed: %s", database_error
        )
    return HealthOut(
        status="ok",
        version=__version__,
        database=database,
        database_error=database_error,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
    )
