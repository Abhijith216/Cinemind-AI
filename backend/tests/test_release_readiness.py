import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api import chat, health, ratings
from app.core import rate_limit
from app.core.config import get_settings
from app.main import app
from app.models import ChatSession, User


@pytest.mark.parametrize("available", [True, False])
def test_readiness_fails_closed_and_hides_database_details(monkeypatch, available: bool) -> None:
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=None if available else RuntimeError("private-host-password"))
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(health, "get_sessionmaker", lambda: lambda: context)
    response = TestClient(app).get("/ready")
    assert response.status_code == (200 if available else 503)
    assert "private-host-password" not in response.text
    assert TestClient(app).get("/api/ready").status_code == response.status_code


def test_forged_bearer_and_forwarding_headers_do_not_rotate_identity() -> None:
    def request(token: str, forwarded: str) -> Request:
        return Request(
            {
                "type": "http",
                "client": ("203.0.113.8", 1000),
                "headers": [
                    (b"authorization", ("Bearer " + token).encode()),
                    (b"x-forwarded-for", forwarded.encode()),
                ],
            }
        )

    assert rate_limit._client_key(request("first", "one")) == rate_limit._client_key(
        request("second", "two")
    )


async def test_shared_limiter_fails_closed_when_database_is_unavailable(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "database")
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 2)
    monkeypatch.setattr(rate_limit, "database_check", AsyncMock(side_effect=TimeoutError()))
    with pytest.raises(HTTPException) as error:
        await rate_limit._limiter_dependency("chat")(
            Request({"type": "http", "client": ("local", 1)})
        )
    assert error.value.status_code == 503
    assert error.value.headers["Retry-After"] == "5"


async def test_rating_delete_rebuilds_preferences_before_commit(monkeypatch) -> None:
    owner = User(id=uuid4(), email="qa@example.invalid", hashed_password="unused")
    record = SimpleNamespace()
    result = SimpleNamespace(scalar_one_or_none=lambda: record)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        delete=AsyncMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    rebuild = AsyncMock()
    monkeypatch.setattr(ratings, "rebuild_taste_profile", rebuild)
    response = await ratings.delete_rating(uuid4(), db, owner)
    assert response.status_code == 204
    db.delete.assert_awaited_once_with(record)
    rebuild.assert_awaited_once_with(db, owner.id)
    db.commit.assert_awaited_once()
    assert owner.id in db.execute.call_args.args[0].compile().params.values()


async def test_failed_preference_rebuild_never_commits_delete(monkeypatch) -> None:
    owner = User(id=uuid4(), email="qa@example.invalid", hashed_password="unused")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: object())),
        delete=AsyncMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(ratings, "rebuild_taste_profile", AsyncMock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        await ratings.delete_rating(uuid4(), db, owner)
    db.commit.assert_not_awaited()


async def test_rating_history_uses_only_actor_and_bounded_pagination() -> None:
    owner = User(id=uuid4(), email="qa@example.invalid", hashed_password="unused")
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[SimpleNamespace(scalar_one=lambda: 60), SimpleNamespace(all=lambda: [])]
        )
    )
    page = await ratings.rating_history(50, 10, db, owner)
    assert page.total == 60 and page.offset == 50
    for call in db.execute.call_args_list:
        assert owner.id in call.args[0].compile().params.values()


async def test_chat_history_requires_account_and_does_not_list_anonymous_capabilities() -> None:
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await chat.list_chat_sessions(0, 20, db, None)
    assert error.value.status_code == 401
    db.execute.assert_not_awaited()


async def test_chat_history_is_owned_and_paginated() -> None:
    owner = uuid4()
    record = ChatSession(id=uuid4(), user_id=owner, updated_at=datetime.datetime.now(datetime.UTC))
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one=lambda: 1),
                SimpleNamespace(all=lambda: [(record, "First request")]),
            ]
        )
    )
    page = await chat.list_chat_sessions(0, 20, db, owner)
    assert page.items[0].title == "First request"
    for call in db.execute.call_args_list:
        assert owner in call.args[0].compile().params.values()


@pytest.mark.parametrize("owner_matches", [True, False])
async def test_chat_delete_enforces_owner_before_any_mutation(owner_matches: bool) -> None:
    owner = uuid4()
    record = ChatSession(id=uuid4(), user_id=owner)
    db = SimpleNamespace(get=AsyncMock(return_value=record), delete=AsyncMock(), commit=AsyncMock())
    if owner_matches:
        assert (await chat.delete_chat_session(record.id, db, owner)).status_code == 204
        db.delete.assert_awaited_once_with(record)
    else:
        with pytest.raises(HTTPException) as error:
            await chat.delete_chat_session(record.id, db, uuid4())
        assert error.value.status_code == 404
        db.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "/api/ratings/history?limit=51",
        "/api/ratings/history?offset=-1",
        "/api/chat/sessions?limit=51",
    ],
)
def test_history_rejects_invalid_page_bounds(path: str) -> None:
    # Unauthenticated rating routes may reject auth before validation; neither can execute a page.
    assert TestClient(app).get(path).status_code in (401, 422)
