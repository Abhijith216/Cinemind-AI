"""Rating endpoints (Module 6) — profile reads live under /users/{id}/."""

import datetime
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.db import get_db_session
from app.models import Movie, Rating, User
from app.schemas.common import MovieOut
from app.schemas.taste import RatedMovieOut, RatingCreate, RatingHistoryOut, RatingOut
from app.services.taste_profile import rebuild_taste_profile

logger = logging.getLogger("app.api.ratings")

router = APIRouter(tags=["ratings"])


@router.get("/ratings/history", response_model=RatingHistoryOut)
async def rating_history(
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=50, ge=1, le=50),
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> RatingHistoryOut:
    total = (
        await db.execute(select(func.count(Rating.id)).where(Rating.user_id == actor.id))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Rating, Movie)
            .join(Movie, Movie.id == Rating.movie_id)
            .where(Rating.user_id == actor.id)
            .order_by(Rating.rated_at.desc(), Rating.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return RatingHistoryOut(
        items=[
            RatedMovieOut(
                id=r.id, movie=MovieOut.model_validate(m), score=r.score, rated_at=r.rated_at
            )
            for r, m in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete("/ratings/{movie_id}", status_code=204)
async def delete_rating(
    movie_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> Response:
    await db.execute(select(User.id).where(User.id == actor.id).with_for_update())
    rating = (
        await db.execute(
            select(Rating).where(Rating.user_id == actor.id, Rating.movie_id == movie_id)
        )
    ).scalar_one_or_none()
    if rating is None:
        raise HTTPException(status_code=404, detail="Rating not found")
    await db.delete(rating)
    await db.flush()
    await rebuild_taste_profile(db, actor.id)
    await db.commit()
    return Response(status_code=204)


@router.post("/ratings", response_model=RatingOut)
async def create_rating(
    payload: RatingCreate,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> RatingOut:
    """Store a rating (upsert per user+movie) and update the taste profile.

    Rating and rebuilt preferences commit together. A correction replaces
    the previous rating's influence instead of accumulating stale tags.
    """
    if payload.user_id != actor.id:
        raise HTTPException(status_code=403, detail="You can only rate movies for your own account")
    # Serialize profile rebuilds for the same account within this transaction.
    await db.execute(select(User.id).where(User.id == actor.id).with_for_update())
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
            rated_at=datetime.datetime.now(datetime.UTC),
        )
        db.add(rating)
        created = True
    else:
        rating.score = payload.score
        created = False

    await db.flush()
    await rebuild_taste_profile(db, actor.id)
    await db.commit()

    response.status_code = 201 if created else 200
    logger.info("Rating and taste profile saved (created=%s)", created)
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


@router.get("/ratings/{movie_id}", response_model=RatingOut | None)
async def read_my_rating(
    movie_id: uuid.UUID,
    actor: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> RatingOut | None:
    rating = (
        await db.execute(
            select(Rating).where(Rating.user_id == actor.id, Rating.movie_id == movie_id)
        )
    ).scalar_one_or_none()
    if rating is None:
        return None
    return RatingOut(
        id=rating.id,
        user_id=rating.user_id,
        movie_id=rating.movie_id,
        score=rating.score,
        rated_at=rating.rated_at,
        created=False,
    )
