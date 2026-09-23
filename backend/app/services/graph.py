"""Recommendation-graph builder (Phase 14 graph view data source).

For one movie and an optional user, returns the movie's node, the user's
highest-rated movies, and one edge per rated movie carrying the CONCRETE
shared genres/keywords — every edge is verifiable data, mirroring the
grounding discipline of the explanation module.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Movie, Rating
from app.schemas.graph import GraphEdge, GraphMovie, RecommendationGraph

_MAX_RATED_MOVIES = 5


def _lower(values: list[object] | None) -> set[str]:
    return {str(value).strip().lower() for value in (values or []) if str(value).strip()}


def _shared(a: list[object] | None, b: list[object] | None) -> list[str]:
    """Case-insensitive intersection, preserving b's display casing."""
    wanted = _lower(a)
    shared: list[str] = []
    seen: set[str] = set()
    for value in b or []:
        key = str(value).strip().lower()
        if key in wanted and key not in seen:
            seen.add(key)
            shared.append(str(value).strip())
    return shared


def _node(movie: Movie, score: float | None = None) -> GraphMovie:
    return GraphMovie(
        id=movie.id,
        title=movie.title or "Untitled",
        release_year=movie.release_year,
        poster_path=movie.poster_path,
        score=score,
    )


async def build_recommendation_graph(
    session: AsyncSession, movie: Movie, user_id: uuid.UUID | None
) -> RecommendationGraph:
    """Assemble the graph for ``movie`` grounded in ``user_id``'s ratings."""
    if user_id is None:
        return RecommendationGraph(
            movie=_node(movie),
            note="Pass user_id to ground the graph in rated movies.",
        )

    rows = (
        (
            await session.execute(
                select(Movie, Rating.score)
                .join(Rating, Rating.movie_id == Movie.id)
                .where(
                    Rating.user_id == user_id,
                    Rating.movie_id != movie.id,
                )
                .order_by(Rating.score.desc())
                .limit(_MAX_RATED_MOVIES)
            )
        )
        .all()
    )

    rated_movies: list[GraphMovie] = []
    edges: list[GraphEdge] = []
    for rated_movie, score in rows:
        rated_movies.append(_node(rated_movie, float(score)))
        edges.append(
            GraphEdge(
                to_movie_id=rated_movie.id,
                shared_genres=_shared(movie.genres, rated_movie.genres),
                shared_keywords=_shared(movie.keywords, rated_movie.keywords),
            )
        )

    note = None if rated_movies else "This user has not rated any movies yet."
    return RecommendationGraph(
        movie=_node(movie), rated_movies=rated_movies, edges=edges, note=note
    )
