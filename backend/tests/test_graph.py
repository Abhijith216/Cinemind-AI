"""Regression coverage for truthful favorite-movie connections."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from app.models import Movie
from app.services.graph import build_recommendation_graph


def movie(title: str, genres: list[str], keywords: list[str] | None = None) -> Movie:
    return Movie(id=uuid4(), tmdb_id=1, title=title, genres=genres, keywords=keywords or [])


async def test_graph_ignores_dislikes_and_unrelated_favorites_before_limit() -> None:
    target = movie("Target", ["Drama"], ["time travel"])
    unrelated = [(movie(f"Unrelated {index}", ["Comedy"]), 10) for index in range(6)]
    matching = movie("A real connection", ["drama"], ["Time Travel"])
    execute = AsyncMock(
        return_value=SimpleNamespace(
            all=lambda: [
                (movie("Disliked", ["Drama"]), 3),
                *unrelated,
                (matching, 7),
            ]
        )
    )
    result = await build_recommendation_graph(SimpleNamespace(execute=execute), target, uuid4())
    assert [node.title for node in result.rated_movies] == [matching.title]
    assert result.edges[0].shared_genres == ["drama"]
    assert result.edges[0].shared_keywords == ["Time Travel"]
    assert "ratings.score >=" in str(execute.call_args.args[0])
    assert result.note is None


async def test_graph_limits_meaningful_connections_to_five() -> None:
    target = movie("Target", ["Drama"])
    rows = [(movie(f"Favorite {index}", ["Drama"]), 9) for index in range(7)]
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)))
    result = await build_recommendation_graph(session, target, uuid4())
    assert len(result.edges) == len(result.rated_movies) == 5


async def test_graph_explains_empty_connections_without_claiming_no_ratings() -> None:
    target = movie("Target", ["Drama"])
    rows = [(movie("Not liked", ["Drama"]), 4), (movie("Unrelated", ["Comedy"]), 9)]
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)))
    result = await build_recommendation_graph(session, target, uuid4())
    assert result.edges == result.rated_movies == []
    assert "rated 7 or higher" in (result.note or "")
