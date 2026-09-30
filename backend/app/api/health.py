"""Health endpoint and app metadata."""


from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.core.db import get_sessionmaker
from app.schemas.common import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Liveness + database reachability probe."""
    database = "up"
    try:
        session = get_sessionmaker()
        async with session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        database = "down"
    return HealthOut(status="ok", version=__version__, database=database)
