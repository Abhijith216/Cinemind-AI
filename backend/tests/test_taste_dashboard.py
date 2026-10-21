"""Privacy and corrections for the complete My Taste flow."""

import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.main import app
from app.models import Movie, User, UserTasteProfile
from app.services.taste_profile import live_taste_evolution, rebuild_taste_profile


@pytest.mark.parametrize("score", [3, 6, 9])
async def test_corrected_ratings_replace_old_preferences(score: int) -> None:
    owner = uuid4()
    movie = Movie(
        id=uuid4(), tmdb_id=1, title="Arrival", genres=["Science Fiction"], keywords=["time"]
    )
    profile = UserTasteProfile(
        user_id=owner,
        likes=["stale like"],
        dislikes=["stale dislike"],
        favorite_themes=["stale theme"],
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(movie, score)])),
        get=AsyncMock(return_value=profile),
    )
    await rebuild_taste_profile(session, owner)
    assert profile.likes == (["Science Fiction", "time"] if score >= 7 else [])
    assert profile.dislikes == (["Science Fiction", "time"] if score <= 4 else [])
    assert profile.favorite_themes == (["time"] if score >= 7 else [])


async def test_timeline_uses_saved_ratings_without_snapshot_rows() -> None:
    owner = uuid4()
    rows = [
        (["Comedy"], ["friendship"], 9, datetime.datetime(2026, 10, 21, tzinfo=datetime.UTC)),
        (["Drama"], ["family"], 8, datetime.datetime(2026, 9, 1, tzinfo=datetime.UTC)),
    ]
    execute = AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    result = await live_taste_evolution(SimpleNamespace(execute=execute), owner)
    assert [row["month"] for row in result] == ["2026-09", "2026-10"]
    assert result[-1]["dominant_themes"] == ["friendship"]
    assert "ratings.score >=" in str(execute.call_args.args[0])


@pytest.fixture
def private_api() -> Any:
    owner = User(id=uuid4(), email="test@example.test", hashed_password="unused")
    database = SimpleNamespace(execute=AsyncMock(), get=AsyncMock())

    async def session() -> Any:
        yield database

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        yield TestClient(app), owner, database
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("route", ["taste-profile", "taste-evolution", "taste-dashboard"])
def test_cannot_read_another_accounts_preferences(private_api: Any, route: str) -> None:
    client, _, database = private_api
    response = client.get(f"/api/users/{uuid4()}/{route}")
    assert response.status_code == 403
    database.execute.assert_not_awaited()


def test_cannot_submit_a_rating_for_another_account(private_api: Any) -> None:
    client, _, database = private_api
    response = client.post(
        "/api/ratings", json={"user_id": str(uuid4()), "movie_id": str(uuid4()), "score": 9}
    )
    assert response.status_code == 403
    database.execute.assert_not_awaited()


def test_signed_out_cannot_read_taste_or_post_scores(private_api: Any) -> None:
    client, owner, _ = private_api
    app.dependency_overrides.pop(get_current_user)
    assert client.get(f"/api/users/{owner.id}/taste-dashboard").status_code == 401
    assert client.get(f"/api/ratings/{uuid4()}").status_code == 401
    assert (
        client.post(
            "/api/ratings", json={"user_id": str(owner.id), "movie_id": str(uuid4()), "score": 9}
        ).status_code
        == 401
    )


def test_personal_graph_cannot_leak_someone_elses_ratings(private_api: Any) -> None:
    client, owner, database = private_api
    result = client.get(
        f"/api/movies/{uuid4()}/recommendation-graph?user_id={uuid4()}",
        headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
    )
    assert result.status_code == 403
    database.execute.assert_not_awaited()


def test_personal_search_cannot_use_someone_elses_ratings(private_api: Any) -> None:
    client, owner, database = private_api
    result = client.post(
        "/api/search/hybrid",
        json={"query": "a comedy", "user_id": str(uuid4())},
        headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
    )
    assert result.status_code == 403
    database.execute.assert_not_awaited()
