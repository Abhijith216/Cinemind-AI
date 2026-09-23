"""Tests for Module 6 taste profile (offline: fake sessions, no Postgres)."""

import datetime
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db_session
from app.main import app
from app.models import Movie, Rating, TasteSnapshot, User, UserTasteProfile
from app.schemas.taste import TasteProfileOut
from app.services.taste_profile import (
    MAX_DOMINANT_ITEMS,
    MAX_PROFILE_ITEMS,
    MonthRating,
    compute_dominant,
    get_taste_profile,
    merge_tags,
    month_window,
    update_taste_profile,
)

# --- fakes ---------------------------------------------------------------------


class _RowsResult:
    """execute() result exposing .all() (rating/snapshot selects)."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _GetResult:
    """execute() result exposing .scalar_one_or_none()."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """Minimal AsyncSession double: get/add/commit + scripted execute()."""

    def __init__(self) -> None:
        self.objects: dict[tuple[type, Any], Any] = {}
        self.added: list[Any] = []
        self.execute_results: list[Any] = []
        self.commits = 0

    def register(self, *objects: Any) -> None:
        for obj in objects:
            key = obj.user_id if isinstance(obj, UserTasteProfile) else obj.id
            self.objects[(type(obj), key)] = obj

    async def get(self, model: Any, key: Any) -> Any:
        found = self.objects.get((model, key))
        if found is not None:
            return found
        # Like the real identity map: objects added this session are gettable.
        for obj in self.added:
            if isinstance(obj, model):
                obj_key = (
                    obj.user_id
                    if isinstance(obj, UserTasteProfile)
                    else getattr(obj, "id", None)
                )
                if obj_key == key:
                    return obj
        return None

    async def execute(self, _statement: Any) -> Any:
        if not self.execute_results:
            raise AssertionError("unexpected execute() call")
        return self.execute_results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _movie(**kwargs: Any) -> Movie:
    return Movie(
        id=uuid.uuid4(),
        tmdb_id=kwargs.pop("tmdb_id", 1),
        title=kwargs.pop("title", "Arrival"),
        genres=kwargs.pop("genres", ["Science Fiction", "Drama"]),
        keywords=kwargs.pop("keywords", ["first contact", "time"]),
        **kwargs,
    )


# --- merge_tags (bounded recency = decay + dedup) --------------------------------


def test_merge_tags_dedupes_case_insensitive_newest_first() -> None:
    merged = merge_tags(["sci-fi", "drama"], ["Sci-Fi", "space"])
    # Each tag once, additions first; the newest casing ("Sci-Fi") wins.
    assert merged == ["Sci-Fi", "space", "drama"]


def test_merge_tags_caps_lists_so_they_never_grow_unbounded() -> None:
    existing = [f"tag-{index:03d}" for index in range(MAX_PROFILE_ITEMS)]
    merged = merge_tags(existing, ["fresh-tag"])
    assert len(merged) == MAX_PROFILE_ITEMS
    assert merged[0] == "fresh-tag"
    assert "tag-049" not in merged  # oldest entry decayed off the end


# --- update_taste_profile ----------------------------------------------------------


@pytest.mark.asyncio
async def test_liked_rating_merges_genres_keywords_and_themes() -> None:
    session = FakeSession()
    movie = _movie()

    result = await update_taste_profile(session, uuid.uuid4(), movie, score=8)

    assert result.action == "liked"
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    assert profile.likes == ["Science Fiction", "Drama", "first contact", "time"]
    assert profile.favorite_themes == ["first contact", "time"]
    assert profile.dislikes == []
    assert session.commits == 1


@pytest.mark.asyncio
async def test_disliked_rating_merges_into_dislikes_only() -> None:
    session = FakeSession()

    result = await update_taste_profile(session, uuid.uuid4(), _movie(), score=3)

    assert result.action == "disliked"
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    assert "Science Fiction" in profile.dislikes
    assert profile.likes == []
    assert profile.favorite_themes == []


@pytest.mark.asyncio
async def test_mid_rating_is_neutral_and_changes_nothing() -> None:
    session = FakeSession()

    result = await update_taste_profile(session, uuid.uuid4(), _movie(), score=6)

    assert result.action == "neutral"
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    assert profile.likes == [] and profile.dislikes == []


@pytest.mark.asyncio
async def test_update_merges_into_existing_profile() -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    existing = UserTasteProfile(
        user_id=user_id, likes=["time"], dislikes=[], favorite_themes=["time"]
    )
    session.register(existing)

    await update_taste_profile(session, user_id, _movie(), score=9)

    assert existing.likes[0] == "Science Fiction"  # newest first
    assert "time" in existing.likes
    assert existing.favorite_themes == ["first contact", "time"]
    assert session.added == []  # no duplicate profile row created


@pytest.mark.asyncio
async def test_like_then_dislike_keeps_lists_independent() -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    movie = _movie()

    await update_taste_profile(session, user_id, movie, score=10)
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    session.register(profile)

    await update_taste_profile(session, user_id, movie, score=2)

    assert "Science Fiction" in profile.likes  # earlier like is preserved
    assert "Science Fiction" in profile.dislikes


# --- get_taste_profile ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_taste_profile_none_when_never_rated() -> None:
    session = FakeSession()
    assert await get_taste_profile(session, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_taste_profile_returns_current_lists() -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    session.register(
        UserTasteProfile(
            user_id=user_id,
            likes=["sci-fi"],
            dislikes=["gore"],
            favorite_themes=["time"],
        )
    )

    profile = await get_taste_profile(session, user_id)

    assert isinstance(profile, TasteProfileOut)
    assert profile.likes == ["sci-fi"]
    assert profile.dislikes == ["gore"]
    assert profile.favorite_themes == ["time"]


# --- month_window + compute_dominant ---------------------------------------------------


def test_month_window_bounds() -> None:
    start, end = month_window("2026-09")
    assert start == datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)


def test_month_window_rolls_over_december() -> None:
    start, end = month_window("2025-12")
    assert start == datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)
    assert end == datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def test_month_window_rejects_garbage() -> None:
    with pytest.raises((ValueError, IndexError)):
        month_window("not-a-month")


def test_compute_dominant_weights_by_score_sum() -> None:
    ratings = [
        MonthRating(genres=["Science Fiction"], keywords=["time"], score=10),
        MonthRating(genres=["Drama"], keywords=["time"], score=7),
        MonthRating(genres=["Drama"], keywords=["identity"], score=8),
    ]
    genres, themes = compute_dominant(ratings)
    # Drama: 7+8=15 beats sci-fi's 10 despite fewer...
    assert genres[0] == "drama"
    assert genres[1] == "science fiction"
    # "time" touched by both ratings (17) beats "identity" (8).
    assert themes == ["time", "identity"]


def test_compute_dominant_tie_breaks_by_count_then_name() -> None:
    ratings = [
        MonthRating(genres=["Drama", "Action"], keywords=[], score=5),
        MonthRating(genres=["Action"], keywords=[], score=5),
        MonthRating(genres=["Comedy"], keywords=[], score=10),
    ]
    genres, _ = compute_dominant(ratings)
    # comedy and action tie on weight (10); action's higher count wins the
    # documented count-then-name tiebreak.
    assert genres == ["action", "comedy", "drama"]


def test_compute_dominant_caps_at_five() -> None:
    many = [
        MonthRating(genres=[f"genre-{index}"], keywords=[], score=5)
        for index in range(8)
    ]
    genres, _ = compute_dominant(many)
    assert len(genres) == MAX_DOMINANT_ITEMS


# --- snapshot_monthly ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_monthly_creates_row() -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    session.execute_results = [
        _RowsResult(
            [
                (["Science Fiction", "Drama"], ["time"], 10),
                (["Drama"], ["identity"], 8),
            ]
        ),
        _GetResult(None),  # no existing snapshot row
    ]

    snapshot = await update_and_snapshot(session, user_id, "2026-09")

    assert snapshot is not None
    assert snapshot.month == "2026-09"
    assert snapshot.dominant_genres[0] == "drama"
    assert snapshot.dominant_themes[0] == "time"
    assert session.commits == 1


async def update_and_snapshot(
    session: FakeSession, user_id: uuid.UUID, month: str
) -> TasteSnapshot | None:
    from app.services.taste_profile import snapshot_monthly

    return await snapshot_monthly(session, user_id, month=month)


@pytest.mark.asyncio
async def test_snapshot_monthly_updates_existing_row() -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    existing = TasteSnapshot(
        user_id=user_id, month="2026-09", dominant_genres=["old"], dominant_themes=[]
    )
    session.execute_results = [
        _RowsResult([(["Comedy"], ["gag"], 9)]),
        _GetResult(existing),
    ]

    snapshot = await update_and_snapshot(session, user_id, "2026-09")

    assert snapshot is existing  # upsert, not a duplicate row
    assert snapshot.dominant_genres == ["comedy"]
    assert session.added == []


@pytest.mark.asyncio
async def test_snapshot_monthly_writes_nothing_without_ratings() -> None:
    session = FakeSession()
    session.execute_results = [_RowsResult([])]

    result = await update_and_snapshot(session, uuid.uuid4(), "2026-09")

    assert result is None
    assert session.added == []
    assert session.commits == 0


# --- endpoints (offline via dependency override) --------------------------------------------


@pytest.fixture
def api() -> Any:
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _override(session: FakeSession) -> None:
    async def _yield_session() -> AsyncGenerator[FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _yield_session


def test_ratings_and_profile_routes_are_registered(api: Any) -> None:
    schema = api.get("/openapi.json").json()
    assert "/api/ratings" in schema["paths"]
    assert "/api/taste-profile/{user_id}" in schema["paths"]


def test_post_rating_creates_rating_and_profile(api: Any) -> None:
    session = FakeSession()
    user = User(id=uuid.uuid4(), email="t@t.dev", hashed_password="x")
    movie = _movie()
    session.register(user, movie)
    session.execute_results = [_GetResult(None)]  # no existing rating
    _override(session)

    response = api.post(
        "/api/ratings",
        json={
            "user_id": str(user.id),
            "movie_id": str(movie.id),
            "score": 9,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["score"] == 9 and body["created"] is True
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    assert "first contact" in profile.likes
    assert session.commits >= 1


def test_post_rating_upserts_existing(api: Any) -> None:
    session = FakeSession()
    user = User(id=uuid.uuid4(), email="t@t.dev", hashed_password="x")
    movie = _movie()
    rating = Rating(
        id=uuid.uuid4(),
        user_id=user.id,
        movie_id=movie.id,
        score=4,
        rated_at=datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC),
    )
    session.register(user, movie)
    session.execute_results = [_GetResult(rating)]
    _override(session)

    response = api.post(
        "/api/ratings",
        json={"user_id": str(user.id), "movie_id": str(movie.id), "score": 8},
    )

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert rating.score == 8


def test_post_rating_rejects_unknown_user_and_movie(api: Any) -> None:
    session = FakeSession()
    movie = _movie()
    session.register(movie)
    _override(session)

    missing_user = api.post(
        "/api/ratings",
        json={"user_id": str(uuid.uuid4()), "movie_id": str(movie.id), "score": 5},
    )
    assert missing_user.status_code == 404

    user = User(id=uuid.uuid4(), email="t@t.dev", hashed_password="x")
    session.register(user)
    session.execute_results = []
    missing_movie = api.post(
        "/api/ratings",
        json={"user_id": str(user.id), "movie_id": str(uuid.uuid4()), "score": 5},
    )
    assert missing_movie.status_code == 404


def test_post_rating_validates_score_range(api: Any) -> None:
    _override(FakeSession())
    response = api.post(
        "/api/ratings",
        json={"user_id": str(uuid.uuid4()), "movie_id": str(uuid.uuid4()), "score": 11},
    )
    assert response.status_code == 422


def test_get_taste_profile_round_trip(api: Any) -> None:
    session = FakeSession()
    user_id = uuid.uuid4()
    movie = _movie()
    user = User(id=user_id, email="t@t.dev", hashed_password="x")
    session.register(user, movie)
    session.execute_results = [_GetResult(None)]
    _override(session)

    created = api.post(
        "/api/ratings",
        json={"user_id": str(user_id), "movie_id": str(movie.id), "score": 9},
    )
    assert created.status_code == 201

    # Same session now holds the (added) profile; serve it via get().
    profile = next(obj for obj in session.added if isinstance(obj, UserTasteProfile))
    session.register(profile)

    fetched = api.get(f"/api/taste-profile/{user_id}")
    assert fetched.status_code == 200
    assert "Science Fiction" in fetched.json()["likes"]
    assert fetched.json()["favorite_themes"] == ["first contact", "time"]


def test_get_taste_profile_404_without_profile(api: Any) -> None:
    _override(FakeSession())
    response = api.get(f"/api/taste-profile/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "rate a movie first" in response.json()["detail"]
