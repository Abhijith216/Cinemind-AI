"""Health endpoint and app metadata."""

import datetime
import time

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.core.db import get_sessionmaker
from app.schemas.common import HealthOut

router = APIRouter(tags=["health"])

_STARTED_AT = time.time()


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness + database reachability probe (200 even if the DB is down)."""
    database = "up"
    try:
        session = get_sessionmaker()
        async with session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health must never 500
        database = "down"
    return HealthOut(
        status="ok",
        version=__version__,
        database=database,
        uptime_seconds=round(time.time() - _STARTED_AT, 1),
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
    )
