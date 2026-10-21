"""User endpoints: taste profile + taste evolution."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.db import get_db_session
from app.models import Movie, Rating, User
from app.schemas.common import MovieOut
from app.schemas.taste import (
    RatedMovieOut,
    TasteDashboardOut,
    TasteProfileOut,
    TasteRecommendationOut,
    TasteSnapshotOut,
)
from app.services.explain import template_explanation
from app.services.personalization import load_taste_signals, taste_matches, unrated_by
from app.services.taste_profile import get_taste_profile, live_taste_evolution

logger = logging.getLogger("app.api.users")

router = APIRouter(prefix="/users", tags=["users"])


def require_owner(user_id: uuid.UUID, actor: User) -> None:
    if actor.id != user_id:
        raise HTTPException(status_code=403, detail="You can only view your own taste profile")


@router.get("/{user_id}/taste-profile", response_model=TasteProfileOut)
async def read_taste_profile(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> TasteProfileOut:
    """The user's current likes/dislikes/favorite themes (404 until first rating)."""
    require_owner(user_id, actor)
    profile = await get_taste_profile(db, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="no taste profile yet — rate a movie first")
    return profile


@router.get("/{user_id}/taste-evolution", response_model=list[TasteSnapshotOut])
async def read_taste_evolution(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> list[TasteSnapshotOut]:
    """The user's monthly snapshots, oldest first ([] if none yet)."""
    require_owner(user_id, actor)
    return [TasteSnapshotOut.model_validate(row) for row in await live_taste_evolution(db, user_id)]


@router.get("/{user_id}/taste-dashboard", response_model=TasteDashboardOut)
async def read_taste_dashboard(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_user),
) -> TasteDashboardOut:
    require_owner(user_id, actor)
    profile = await get_taste_profile(db, user_id)
    total, average = (
        await db.execute(
            select(func.count(Rating.id), func.avg(Rating.score)).where(Rating.user_id == user_id)
        )
    ).one()
    rows = (
        await db.execute(
            select(Rating, Movie)
            .join(Movie, Movie.id == Rating.movie_id)
            .where(Rating.user_id == user_id)
            .order_by(Rating.rated_at.desc(), Rating.id)
            .limit(50)
        )
    ).all()
    recommendations = []
    taste = await load_taste_signals(db, user_id)
    if any(weight > 0 for weight in [*taste.genres.values(), *taste.keywords.values()]):
        affinity = taste.sql_affinity()
        recommendations = list(
            (
                await db.execute(
                    select(Movie)
                    .where(
                        unrated_by(user_id),
                        affinity > 0,
                    )
                    .order_by(affinity.desc(), Movie.vote_count.desc().nullslast(), Movie.id)
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
    return TasteDashboardOut(
        profile=profile,
        total_ratings=total,
        average_score=float(average) if average is not None else None,
        ratings=[
            RatedMovieOut(
                id=rating.id,
                movie=MovieOut.model_validate(movie),
                score=rating.score,
                rated_at=rating.rated_at,
            )
            for rating, movie in rows
        ],
        recommendations=[
            TasteRecommendationOut(
                **MovieOut.model_validate(movie).model_dump(),
                explanation=template_explanation(matches, movie.title),
                matched_attributes=matches,
                preference_score=taste.affinity(movie),
            )
            for movie in recommendations
            for matches in [taste_matches(movie, taste)]
        ],
    )
