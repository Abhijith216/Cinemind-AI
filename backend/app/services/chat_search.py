"""AI intent to catalog retrieval with deterministic, factual explanations."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Movie
from app.schemas.explanation import Explanation, UserTasteContext
from app.schemas.intent import QueryIntent
from app.services.catalog_search import catalog_search
from app.services.chat_orchestrator import _filters_from_intent, render_intent_text
from app.services.explain import compute_matched_attributes, template_explanation
from app.services.ingestion import TMDbError
from app.services.personalization import load_taste_signals
from app.services.retrieval import RankedMovie, jaccard_similarity
from app.services.tmdb_sync import resolve_references

logger = logging.getLogger("app.chat_search")


async def search_intent_catalog(
    session: AsyncSession,
    intent: QueryIntent,
    user_id: UUID | None,
    limit: int,
) -> list[RankedMovie]:
    try:
        await resolve_references(session, intent.similar_to)
    except (TMDbError, KeyError, ValueError, TypeError):
        # An optional metadata provider outage must not disable the saved catalog.
        logger.warning("TMDb reference lookup unavailable; using saved catalog")
    results = await catalog_search(
        session,
        render_intent_text(intent),
        _filters_from_intent(intent),
        max(100, limit * 5),
        intent=intent,
        exclude_rated_by=user_id,
    )
    taste = await load_taste_signals(session, user_id)
    ranked = [
        RankedMovie(
            movie=Movie(**item.movie.model_dump()),
            # Request relevance stays dominant; history reranks nearby eligible candidates.
            final_score=1 / (1 + position / 10)
            + 0.35 * taste.affinity(Movie(**item.movie.model_dump())),
            semantic_similarity=0,
            user_history_match=taste.affinity(Movie(**item.movie.model_dump())),
            genre_similarity=jaccard_similarity(intent.genres_include, item.movie.genres),
            normalized_rating=(item.movie.vote_average or 0) / 10,
            normalized_popularity=0,
        )
        for position, item in enumerate(results)
    ]
    return sorted(ranked, key=lambda item: -item.final_score)[:limit]


async def explain_catalog_match(
    movie: Movie,
    intent: QueryIntent | None,
    taste: UserTasteContext | None,
) -> Explanation:
    matches = compute_matched_attributes(movie, intent, taste)
    return Explanation(
        movie_id=str(movie.id),
        movie_title=movie.title,
        text=template_explanation(matches, movie.title),
        matched_attributes=matches,
        source="template",
        query_intent=intent,
    )
