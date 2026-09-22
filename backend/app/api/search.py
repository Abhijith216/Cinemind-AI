"""Search endpoints (Module 3)."""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.schemas.common import MovieOut
from app.schemas.retrieval import (
    ComponentScores,
    RankedMovieOut,
    SearchRequest,
    SearchResponse,
)
from app.services.retrieval import (
    WEIGHT_GENRE,
    WEIGHT_HISTORY,
    WEIGHT_POPULARITY,
    WEIGHT_RATING,
    WEIGHT_SEMANTIC,
    embed_query,
    hybrid_search,
)

logger = logging.getLogger("app.api.search")

router = APIRouter(tags=["search"])


@router.post("/search/hybrid", response_model=SearchResponse)
async def search_hybrid(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db_session),
) -> SearchResponse:
    """Embed the raw text query, run hybrid retrieval, return ranked movies.

    Each result carries its full component breakdown so the weighting can be
    debugged directly from the response.
    """
    logger.info("hybrid search: %r (user=%s)", request.query[:80], request.user_id)
    query_embedding = await embed_query(request.query)
    ranked = await hybrid_search(
        session=db,
        query_embedding=query_embedding,
        filters=request.filters,
        user_id=request.user_id,
        limit=request.limit,
    )
    return SearchResponse(
        query=request.query,
        results=[
            RankedMovieOut(
                movie=MovieOut.model_validate(item.movie),
                final_score=item.final_score,
                components=ComponentScores(
                    semantic_similarity=item.semantic_similarity,
                    user_history_match=item.user_history_match,
                    genre_similarity=item.genre_similarity,
                    normalized_rating=item.normalized_rating,
                    normalized_popularity=item.normalized_popularity,
                ),
            )
            for item in ranked
        ],
        applied_weights={
            "semantic": WEIGHT_SEMANTIC,
            "history": WEIGHT_HISTORY,
            "genre": WEIGHT_GENRE,
            "rating": WEIGHT_RATING,
            "popularity": WEIGHT_POPULARITY,
        },
    )
