"""Real preference signals, candidate reranking, disclosure and privacy regressions."""

import datetime
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.dialects.postgresql import dialect

from app.api import users
from app.models import Movie, User
from app.schemas.common import MovieOut
from app.schemas.intent import QueryIntent
from app.schemas.retrieval import DiscoverMovieOut
from app.services import chat_search
from app.services.chat_orchestrator import build_conversational_reply, release_window
from app.services.llm_client import ChatLLMClient, LLMError
from app.services.personalization import (
    MAX_KEYWORDS,
    TasteSignals,
    load_taste_signals,
    rating_signal,
    signals_from_ratings,
    taste_matches,
    unrated_by,
)


def movie(title: str, genres: list[str], keywords: list[str] | None = None) -> Movie:
    return Movie(id=uuid4(), tmdb_id=1, title=title, genres=genres, keywords=keywords or [])


@pytest.mark.parametrize(
    ("score", "expected"), [(1, -1), (4, -0.25), (5, 0), (6, 0), (7, 0.25), (10, 1)]
)
def test_rating_thresholds(score: int, expected: float) -> None:
    assert rating_signal(score) == expected


def test_conflicting_scores_cancel_and_corrected_ratings_remove_likes() -> None:
    liked = movie("Favorite", ["Comedy"], ["friendship"])
    disliked = movie("Disliked", ["comedy"], ["friendship"])
    neutral = movie("Neutral", ["Comedy"], ["friendship"])
    signals = signals_from_ratings([(liked, 10), (disliked, 1), (neutral, 6)])
    assert signals.affinity(liked) == 0
    assert signals_from_ratings([(liked, 3)]).affinity(liked) < 0
    assert signals_from_ratings([(liked, 7)]).affinity(liked) > 0
    assert signals.context.loved_movies[0].title == "Favorite"


def test_signal_bounds_and_factual_matches() -> None:
    favorite = movie("Favorite", ["Comedy"], [f"theme {i}" for i in range(200)])
    signals = signals_from_ratings([(favorite, 10)])
    assert len(signals.keywords) == MAX_KEYWORDS
    assert -1 <= signals.affinity(favorite) <= 1
    candidate = movie("Candidate", ["Comedy", "Drama"], ["theme 0", "unrelated"])
    matches = taste_matches(candidate, signals)
    assert matches.genres == ["Comedy"]
    assert matches.themes == ["theme 0"]
    assert "Favorite" in matches.loved_movie_overlaps[0].label


async def test_own_rating_query_is_bounded_but_all_rated_movies_are_excluded() -> None:
    owner = uuid4()
    execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    await load_taste_signals(SimpleNamespace(execute=execute), owner)
    statement = execute.call_args.args[0]
    compiled = statement.compile(dialect=dialect())
    assert owner in compiled.params.values()
    assert 500 in compiled.params.values()
    exclusion = unrated_by(owner).compile(dialect=dialect())
    assert owner in exclusion.params.values()
    assert "LIMIT" not in str(exclusion)
    execute.reset_mock()
    await load_taste_signals(SimpleNamespace(execute=execute), None)
    execute.assert_not_awaited()


@pytest.mark.parametrize("personalized", [False, True])
async def test_chat_reranks_before_limit_without_changing_request_filters(
    monkeypatch: pytest.MonkeyPatch, personalized: bool
) -> None:
    candidates = [movie("Less your taste", ["Action"]), movie("Your taste", ["Comedy"])]
    search = AsyncMock(
        return_value=[
            DiscoverMovieOut(movie=MovieOut.model_validate(m), explanation="", matched_terms=[])
            for m in candidates
        ]
    )
    monkeypatch.setattr(chat_search, "catalog_search", search)
    monkeypatch.setattr(chat_search, "resolve_references", AsyncMock())
    taste = TasteSignals(genres={"Comedy": 1, "Action": -1}) if personalized else TasteSignals()
    monkeypatch.setattr(chat_search, "load_taste_signals", AsyncMock(return_value=taste))
    owner = uuid4() if personalized else None
    intent = QueryIntent(genres_include=["Comedy"], genres_exclude=["Horror"], runtime_max=90)
    ranked = await chat_search.search_intent_catalog(SimpleNamespace(), intent, owner, 1)
    assert ranked[0].movie.title == ("Your taste" if personalized else "Less your taste")
    assert ranked[0].user_history_match == (0.65 if personalized else 0)
    filters = search.call_args.args[2]
    assert filters.genres == ["Comedy"]
    assert filters.excluded_genres == ["Horror"]
    assert filters.max_runtime == 90
    assert search.call_args.args[3] >= 100
    assert search.call_args.kwargs["exclude_rated_by"] == owner


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("2025", (2025, 2025)),
        ("1990s", (1990, 1999)),
        ("2020-2026", (2020, 2026)),
        ("2026-2020", (None, None)),
        ("recent", (datetime.date.today().year - 5, None)),
        ("historical", (None, None)),
    ],
)
def test_release_years_ranges_and_unsupported_periods(period: str, expected: tuple) -> None:
    assert release_window(period) == expected


def test_unsupported_preferences_are_visible_even_with_no_results() -> None:
    reply = build_conversational_reply(
        QueryIntent(
            pace="slow-burn",
            violence_tolerance="none",
            ending_type="happy",
            time_period="historical",
        ),
        [],
    )
    assert "couldn't apply your pace preference" in reply
    assert "aren't guaranteed to meet your violence preference" in reply
    assert "endings aren't verified" in reply
    assert "couldn't apply that release period" in reply


async def test_dashboard_serializes_explanations_and_same_affinity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = User(id=uuid4(), email="qa@example.invalid", hashed_password="unused")
    favorite = movie("Favorite", ["Comedy"], ["friendship"])
    candidate = movie("New pick", ["Comedy"], ["friendship"])
    signals = signals_from_ratings([(favorite, 7)])
    monkeypatch.setattr(users, "get_taste_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(users, "load_taste_signals", AsyncMock(return_value=signals))
    execute = AsyncMock(
        side_effect=[
            SimpleNamespace(one=lambda: (1, 7)),
            SimpleNamespace(all=lambda: []),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [candidate])),
        ]
    )
    result = await users.read_taste_dashboard(owner.id, SimpleNamespace(execute=execute), owner)
    suggestion = result.recommendations[0]
    assert suggestion.id == candidate.id
    assert suggestion.preference_score == signals.affinity(candidate)
    assert "Favorite (7/10)" in suggestion.explanation
    assert suggestion.matched_attributes.themes == ["friendship"]
    statement = execute.call_args.args[0].compile(dialect=dialect())
    assert owner.id in statement.params.values()


async def test_provider_telemetry_categorizes_failure_without_response_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.llm")
    client = ChatLLMClient(
        "private-test-key",
        model="test",
        base_url="https://provider.example/v1",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(402, json={"error": "private-provider-body"})
        ),
    )
    try:
        with pytest.raises(LLMError) as error:
            await client.complete_json(
                system_prompt="JSON", user_prompt="comedy", schema_model=QueryIntent
            )
        assert error.value.category == "credits"
        assert "category=credits" in caplog.text and "duration_ms=" in caplog.text
        assert "private-test-key" not in caplog.text and "private-provider-body" not in caplog.text
    finally:
        await client.aclose()
