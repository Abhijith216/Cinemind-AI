"""Movie endpoints: detail + recommendation graph."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models import Movie
from app.schemas.common import MovieOut
from app.schemas.graph import RecommendationGraph
from app.services.graph import build_recommendation_graph

logger = logging.getLogger("app.api.movies")

router = APIRouter(tags=["movies"])


async def _get_movie_or_404(db: AsyncSession, movie_id: uuid.UUID) -> Movie:
    movie = await db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status_code=404, detail="movie not found")
    return movie


@router.get("/movies/{movie_id}", response_model=MovieOut)
async def get_movie(
    movie_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> MovieOut:
    """Full public representation of one movie."""
    return MovieOut.model_validate(await _get_movie_or_404(db, movie_id))


@router.get("/movies/{movie_id}/recommendation-graph", response_model=RecommendationGraph)
async def get_recommendation_graph(
    movie_id: uuid.UUID,
    user_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> RecommendationGraph:
    """The structured "why" graph: movie ↔ shared attributes ↔ rated movies.

    Grounds the graph in ``user_id``'s ratings when provided; otherwise
    returns the movie node with an explanatory note.
    """
    movie = await _get_movie_or_404(db, movie_id)
    return await build_recommendation_graph(db, movie, user_id)
