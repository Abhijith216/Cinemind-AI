"""Tests for hybrid retrieval (offline: fake DB rows, no Postgres)."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Movie
from app.schemas.retrieval import SearchFilters
from app.services.retrieval import (
    CANDIDATE_LIMIT,
    WEIGHT_GENRE,
    WEIGHT_HISTORY,
    WEIGHT_POPULARITY,
    WEIGHT_RATING,
    WEIGHT_SEMANTIC,
    cosine_similarity,
    fetch_user_history_vector,
    jaccard_similarity,
    min_max_normalize,
    re_rank,
)


def _movie(
    *,
    genres: list[str] | None = None,
    personality: dict[str, int] | None = None,
    vote_average: float | None = 7.0,
    popularity: float | None = 100.0,
) -> Movie:
    movie = Movie(
        tmdb_id=1,
        title="Test Movie",
        genres=genres or [],
        keywords=[],
        vote_average=vote_average,
        popularity=popularity,
    )
    movie.personality = personality
    return movie


# --- Component math ------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    assert (
        WEIGHT_SEMANTIC
        + WEIGHT_HISTORY
        + WEIGHT_GENRE
        + WEIGHT_RATING
        + WEIGHT_POPULARITY
        == pytest.approx(1.0)
    )


def test_jaccard_similarity() -> None:
    assert jaccard_similarity(["sci-fi", "drama"], ["Sci-Fi", "Drama"]) == 1.0
    assert jaccard_similarity(["sci-fi"], ["drama"]) == 0.0
    assert jaccard_similarity(["sci-fi", "drama"], ["sci-fi", "comedy"]) == pytest.approx(1 / 3)
    assert jaccard_similarity([], ["sci-fi"]) == 0.0  # no query genres → 0
    assert jaccard_similarity(["sci-fi"], []) == 0.0


def test_min_max_normalize() -> None:
    assert min_max_normalize([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]
    assert min_max_normalize([5.0, 5.0, 5.0]) == [0.5, 0.5, 0.5]
    assert min_max_normalize([]) == []


def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)
    assert cosine_similarity([0, 0], [1, 0]) == 0.0  # zero vector is safe
    assert cosine_similarity([1, 2], [1, 2]) == pytest.approx(1.0)


# --- user history --------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any) -> _FakeResult:
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_history_vector_is_none_without_ratings() -> None:
    session = _FakeSession([])
    assert await fetch_user_history_vector(session, uuid4()) is None


@pytest.mark.asyncio
async def test_history_vector_is_none_for_anonymous() -> None:
    session = _FakeSession([{"emotion": 90}])
    assert await fetch_user_history_vector(session, None) is None


@pytest.mark.asyncio
async def test_history_vector_averages_loved_personalities() -> None:
    liked = {
        "emotion": 80,
        "mind_blowing": 60,
        "darkness": 40,
        "humor": 20,
        "violence": 10,
        "romance": 30,
        "hopefulness": 70,
        "plot_complexity": 90,
        "rewatchability": 50,
    }
    session = _FakeSession([liked, liked])
    vector = await fetch_user_history_vector(session, uuid4())
    assert vector is not None
    assert vector[0] == pytest.approx(80.0)
    assert len(vector) == 9


@pytest.mark.asyncio
async def test_history_vector_skips_malformed_personality() -> None:
    session = _FakeSession([{"bogus": True}, {"emotion": "high"}])
    assert await fetch_user_history_vector(session, uuid4()) is None


# --- re-rank --------------------------------------------------------------------


def test_re_rank_applies_the_full_formula() -> None:
    liked = {trait: 50 for trait in (
        "emotion", "mind_blowing", "darkness", "humor", "violence",
        "romance", "hopefulness", "plot_complexity", "rewatchability",
    )}
    movie = _movie(genres=["Sci-Fi"], personality=liked, vote_average=8.0, popularity=200.0)

    ranked = re_rank(
        [(movie, 0.8)],
        query_genres=["sci-fi"],
        history_vector=[50.0] * 9,
    )

    assert len(ranked) == 1
    item = ranked[0]
    expected = (
        0.45 * 0.8   # semantic (already in [0,1])
        + 0.20 * 1.0  # identical personality vectors → cosine 1
        + 0.15 * 1.0  # exact genre match → Jaccard 1
        + 0.10 * 0.5  # single candidate → min-max mid
        + 0.10 * 0.5  # single candidate → min-max mid
    )
    assert item.final_score == pytest.approx(expected)
    assert item.semantic_similarity == pytest.approx(0.8)
    assert item.user_history_match == pytest.approx(1.0)
    assert item.genre_similarity == pytest.approx(1.0)


def test_re_rank_orders_by_final_score() -> None:
    liked = {trait: 50 for trait in (
        "emotion", "mind_blowing", "darkness", "humor", "violence",
        "romance", "hopefulness", "plot_complexity", "rewatchability",
    )}
    # Movie A: weaker semantic but perfect genre + history match.
    movie_a = _movie(genres=["Sci-Fi"], personality=liked, vote_average=7.0, popularity=10.0)
    # Movie B: stronger semantic, wrong genre/personality.
    movie_b = _movie(genres=["Horror"], personality=None, vote_average=7.0, popularity=10.0)

    ranked = re_rank(
        [(movie_b, 0.85), (movie_a, 0.75)],
        query_genres=["sci-fi"],
        history_vector=[50.0] * 9,
    )

    assert [item.movie for item in ranked][0] is movie_a  # re-rank flipped the order


def test_re_rank_without_history_zeros_history_component() -> None:
    movie = _movie(genres=["Sci-Fi"], personality=None)
    ranked = re_rank([(movie, 0.9)], query_genres=[], history_vector=None)
    assert ranked[0].user_history_match == 0.0
    expected = 0.45 * 0.9 + 0.15 * 0.0 + 0.10 * 0.5 + 0.10 * 0.5
    assert ranked[0].final_score == pytest.approx(expected)


def test_re_rank_handles_null_rating_and_popularity() -> None:
    movie = _movie(genres=None, personality=None, vote_average=None, popularity=None)
    ranked = re_rank([(movie, 0.5)], query_genres=[], history_vector=None)
    assert ranked[0].normalized_rating == 0.5
    assert ranked[0].normalized_popularity == 0.5


def test_re_rank_empty_candidates() -> None:
    assert re_rank([], query_genres=[], history_vector=None) == []


# --- pipeline guard rails ---------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_search_rejects_wrong_dimension_embeddings() -> None:
    from app.services.retrieval import hybrid_search

    session = _FakeSession([])
    with pytest.raises(ValueError, match="dims"):
        await hybrid_search(session, [0.1] * 8, SearchFilters(), user_id=None)  # type: ignore[arg-type]


def test_candidate_limit_is_set_for_sql_stage() -> None:
    # The SQL stage must bound the candidate set before Python re-ranking.
    assert CANDIDATE_LIMIT == 200


# --- endpoint wiring (offline) ----------------------------------------------------


def test_search_endpoint_exists_in_openapi() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/api/search/hybrid" in schema["paths"]
    post = schema["paths"]["/api/search/hybrid"]["post"]
    assert set(post["requestBody"]["content"]) == {"application/json"}


def test_search_endpoint_validates_request_body() -> None:
    client = TestClient(app)
    response = client.post("/api/search/hybrid", json={"query": ""})
    assert response.status_code == 422  # empty query rejected by schema
