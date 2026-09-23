"""User endpoints: taste profile + taste evolution."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models import TasteSnapshot, User
from app.schemas.taste import TasteProfileOut, TasteSnapshotOut
from app.services.taste_profile import get_taste_profile

logger = logging.getLogger("app.api.users")

router = APIRouter(prefix="/users", tags=["users"])


async def _user_exists_or_404(db: AsyncSession, user_id: uuid.UUID) -> None:
    if await db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="user not found")


@router.get("/{user_id}/taste-profile", response_model=TasteProfileOut)
async def read_taste_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> TasteProfileOut:
    """The user's current likes/dislikes/favorite themes (404 until first rating)."""
    await _user_exists_or_404(db, user_id)
    profile = await get_taste_profile(db, user_id)
    if profile is None:
        raise HTTPException(
            status_code=404, detail="no taste profile yet — rate a movie first"
        )
    return profile


@router.get("/{user_id}/taste-evolution", response_model=list[TasteSnapshotOut])
async def read_taste_evolution(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> list[TasteSnapshotOut]:
    """The user's monthly snapshots, oldest first ([] if none yet)."""
    await _user_exists_or_404(db, user_id)
    result = await db.execute(
        select(TasteSnapshot)
        .where(TasteSnapshot.user_id == user_id)
        .order_by(TasteSnapshot.month)
    )
    rows: list[Any] = list(result.scalars().all())
    return [
        TasteSnapshotOut(
            user_id=row.user_id,
            month=row.month,
            dominant_genres=[str(tag) for tag in row.dominant_genres],
            dominant_themes=[str(tag) for tag in row.dominant_themes],
            created_at=row.created_at,
        )
        for row in rows
    ]
