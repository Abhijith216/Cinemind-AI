"""Rating + taste-profile endpoints (Module 6)."""

import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models import Movie, Rating, User
from app.schemas.taste import RatingCreate, RatingOut, TasteProfileOut
from app.services.taste_profile import get_taste_profile, update_taste_profile

logger = logging.getLogger("app.api.ratings")

router = APIRouter(tags=["ratings"])


@router.post("/ratings", response_model=RatingOut)
async def create_rating(
    payload: RatingCreate,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> RatingOut:
    """Store a rating (upsert per user+movie) and update the taste profile.

    The profile update shares the request's transaction: the extra commit
    inside ``update_taste_profile`` persists both writes atomically enough
    for now — a crash after it leaves only a harmless committed profile.
    """
    user = await db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    movie = await db.get(Movie, payload.movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie not found")

    existing = await db.execute(
        select(Rating).where(
            Rating.user_id == payload.user_id,
            Rating.movie_id == payload.movie_id,
        )
    )
    rating = existing.scalar_one_or_none()
    if rating is None:
        rating = Rating(
            id=uuid.uuid4(),
            user_id=payload.user_id,
            movie_id=payload.movie_id,
            score=payload.score,
        )
        db.add(rating)
        created = True
    else:
        rating.score = payload.score
        created = False

    result = await update_taste_profile(db, payload.user_id, movie, payload.score)

    response.status_code = 201 if created else 200
    logger.info(
        "rating %d/10 user=%s movie=%s created=%s (profile: %s)",
        payload.score,
        payload.user_id,
        payload.movie_id,
        created,
        result.action,
    )
    return RatingOut(
        id=rating.id,
        user_id=rating.user_id,
        movie_id=rating.movie_id,
        score=rating.score,
        # Server default fills this on the real DB; transient objects (tests)
        # fall back to now.
        rated_at=rating.rated_at or datetime.datetime.now(datetime.UTC),
        created=created,
    )


@router.get("/taste-profile/{user_id}", response_model=TasteProfileOut)
async def read_taste_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> TasteProfileOut:
    """Return the user's current likes/dislikes/favorite themes."""
    profile = await get_taste_profile(db, user_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="no taste profile yet — rate a movie first",
        )
    return profile
