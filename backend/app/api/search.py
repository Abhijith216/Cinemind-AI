"""Search endpoints (Module 3)."""

import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import chat_actor
from app.core.db import ensure_database_connection, get_db_session
from app.core.rate_limit import search_rate_limit
from app.schemas.common import MovieOut
from app.schemas.retrieval import (
    ComponentScores,
    DiscoverResponse,
    RankedMovieOut,
    SearchRequest,
    SearchResponse,
)
from app.services.catalog_search import catalog_search
from app.services.embeddings import EmbeddingError
from app.services.ingestion import TMDbError
from app.services.retrieval import (
    WEIGHT_GENRE,
    WEIGHT_HISTORY,
    WEIGHT_POPULARITY,
    WEIGHT_RATING,
    WEIGHT_SEMANTIC,
    embed_query,
    hybrid_search,
)
from app.services.tmdb_sync import resolve_references

logger = logging.getLogger("app.api.search")

router = APIRouter(tags=["search"])


@router.post("/search/discover", response_model=DiscoverResponse)
async def discover(
    request: SearchRequest,
    _rate_limit: search_rate_limit,
    db: AsyncSession = Depends(get_db_session),
) -> DiscoverResponse:
    """Search real movie metadata; does not require an AI provider."""
    try:
        async with asyncio.timeout(30):
            await ensure_database_connection(db)
            results = await catalog_search(db, request.query, request.filters, request.limit)
            if not results and len(request.query) <= 100:
                try:
                    # Exact title lookup only: never import an arbitrary TMDb
                    # search hit as if it satisfied a mood request.
                    await resolve_references(db, [request.query])
                    results = await catalog_search(
                        db, request.query, request.filters, request.limit
                    )
                except (TMDbError, ValueError, KeyError, TypeError):
                    logger.warning("TMDb lookup unavailable; retained saved catalog results")
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        # Keep database URLs, host names and credentials out of API responses/logs.
        logger.warning("Discover database unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="The movie catalog is temporarily unavailable. Please try again shortly.",
        ) from exc
    return DiscoverResponse(query=request.query, results=results)


@router.post("/search/hybrid", response_model=SearchResponse)
async def search_hybrid(
    request: SearchRequest,
    _rate_limit: search_rate_limit,
    db: AsyncSession = Depends(get_db_session),
    actor: UUID | None = Depends(chat_actor),
) -> SearchResponse:
    """Embed the raw text query, run hybrid retrieval, return ranked movies.

    Each result carries its full component breakdown so the weighting can be
    debugged directly from the response.
    """
    if request.user_id is not None and request.user_id != actor:
        raise HTTPException(
            status_code=403, detail="You can only search with your own taste profile"
        )
    logger.info("Hybrid search requested")
    try:
        query_embedding = await embed_query(request.query)
    except EmbeddingError as exc:
        logger.warning("embedding unavailable for search: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Search is temporarily unavailable — the embedding service did not respond.",
        ) from exc
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
