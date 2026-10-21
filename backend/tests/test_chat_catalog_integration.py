"""Chat/provider/TMDb contract regressions. External calls use explicit fakes."""

import datetime
import json
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql.asyncpg import dialect

from app.api.chat import chat_actor
from app.core.db import get_db_session
from app.core.rate_limit import reset_all_limiters
from app.main import app
from app.models import ChatMessage, ChatSession, Movie
from app.schemas.intent import QueryIntent
from app.schemas.retrieval import SearchFilters
from app.services.catalog_search import catalog_search
from app.services.chat_orchestrator import _filters_from_intent
from app.services.ingestion import TMDbClient, TMDbError, upsert_movie
from app.services.llm_client import ChatLLMClient, LLMError
from app.services.query_understanding import AmbiguousQueryError


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> "Result":
        return self

    def all(self) -> list[Any]:
        return self.rows


class Session:
    async def rollback(self) -> None:
        self.rollbacks += 1

    def __init__(self) -> None:
        self.rollbacks = 0
        self.sessions: dict[Any, ChatSession] = {}
        self.messages: list[ChatMessage] = []
        self.movies = [
            Movie(
                id=uuid4(),
                tmdb_id=1,
                title="Catalog Comedy",
                overview="Friends reunite.",
                runtime=89,
                genres=["Comedy"],
                keywords=["friendship"],
                release_year=2014,
            )
        ]
        self.statements: list[Any] = []

    def add(self, obj: Any) -> None:
        if isinstance(obj, ChatSession):
            self.sessions[obj.id] = obj
        elif isinstance(obj, ChatMessage):
            self.messages.append(obj)

    async def get(self, model: Any, key: Any) -> Any:
        return self.sessions.get(key) if model is ChatSession else None

    async def execute(self, statement: Any) -> Result:
        self.statements.append(statement)
        if "chat_messages" in str(statement):
            rows = sorted(self.messages, key=lambda row: row.created_at)
            if "DESC" in str(statement):
                rows.reverse()
            return Result(rows)
        return Result(self.movies)

    async def commit(self) -> None:
        pass


@pytest.fixture
def api(monkeypatch: Any) -> Any:
    session = Session()

    async def database() -> AsyncGenerator[Session, None]:
        yield session

    async def no_tmdb(*args: Any, **kwargs: Any) -> None:
        pass

    app.dependency_overrides[get_db_session] = database
    monkeypatch.setattr("app.services.chat_search.resolve_references", no_tmdb)
    monkeypatch.setattr("app.api.chat.ensure_database_connection", no_tmdb)
    reset_all_limiters()
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.clear()
        reset_all_limiters()


def test_provider_failure_releases_transaction_without_partial_chat(
    api: Any, monkeypatch: Any
) -> None:
    client, session = api

    async def unavailable(*args: Any, **kwargs: Any) -> QueryIntent:
        assert session.rollbacks == 1
        assert not session.sessions and not session.messages
        raise LLMError("Provider unavailable", status_code=429)

    monkeypatch.setattr("app.api.chat.parse_query", unavailable)
    response = client.post("/api/chat/message", json={"message": "A short comedy"})
    assert response.status_code == 503
    assert not session.sessions and not session.messages


def test_greeting_is_saved_and_restored_when_provider_is_unavailable(
    api: Any, monkeypatch: Any
) -> None:
    client, session = api

    def unavailable() -> None:
        pytest.fail("A greeting must not depend on the AI service")

    monkeypatch.setattr("app.services.query_understanding.create_chat_client", unavailable)
    response = client.post("/api/chat/message", json={"message": "hey"})
    assert response.status_code == 200
    turn = response.json()
    assert turn["asked_clarifying_question"] is True
    assert turn["results"] == []
    assert "What kind of movie" in turn["reply"]
    assert [message.role for message in session.messages] == ["user", "assistant"]
    restored = client.get(f"/api/chat/sessions/{turn['session_id']}")
    assert restored.status_code == 200
    assert restored.json()["messages"][-1]["content"] == turn["reply"]


def test_ai_chat_works_without_embeddings_and_restores_cards(api: Any, monkeypatch: Any) -> None:
    client, session = api
    histories = []

    async def parse(message: str, history: list[dict[str, str]]) -> QueryIntent:
        histories.append(history)
        if message == "surprise me":
            raise AmbiguousQueryError("Would you prefer something funny or tense?")
        return QueryIntent(genres_include=["Comedy"], genres_exclude=["Horror"], runtime_max=90)

    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Catalog-backed AI chat must not request embeddings")

    monkeypatch.setattr("app.api.chat.parse_query", parse)
    monkeypatch.setattr("app.api.chat.embed_query", forbidden)
    first = client.post("/api/chat/message", json={"message": "surprise me"})
    assert first.status_code == 200
    assert first.json()["asked_clarifying_question"] is True
    session_id = first.json()["session_id"]
    second = client.post(
        "/api/chat/message", json={"message": "funny under 90 minutes", "session_id": session_id}
    )
    assert second.status_code == 200, second.text
    assert second.json()["results"][0]["movie"]["title"] == "Catalog Comedy"
    assert len(histories[1]) == 2
    assert len(session.messages) == 4
    replay = client.get(f"/api/chat/sessions/{session_id}")
    assert replay.status_code == 200, replay.text
    assert replay.json()["messages"][-1]["results"][0]["movie"]["title"] == "Catalog Comedy"
    assert replay.json()["messages"][-1]["intent"]["runtime_max"] == 90


def test_private_account_chat_requires_its_owner(api: Any) -> None:
    client, session = api
    owner = uuid4()
    conversation = ChatSession(
        id=uuid4(), user_id=owner, created_at=datetime.datetime.now(datetime.UTC)
    )
    session.add(conversation)
    path = f"/api/chat/sessions/{conversation.id}"
    assert client.get(path).status_code == 404
    assert (
        client.post(
            "/api/chat/message",
            json={
                "message": "continue",
                "session_id": str(conversation.id),
            },
        ).status_code
        == 404
    )
    app.dependency_overrides[chat_actor] = lambda: owner
    assert client.get(path).status_code == 200
    app.dependency_overrides[chat_actor] = lambda: uuid4()
    assert client.get(path).status_code == 404


def test_client_cannot_impersonate_taste_profile(api: Any) -> None:
    client, _ = api
    assert (
        client.post(
            "/api/chat/message",
            json={
                "message": "recommend something",
                "user_id": str(uuid4()),
            },
        ).status_code
        == 403
    )


def test_blank_chat_messages_are_rejected(api: Any) -> None:
    client, _ = api
    assert client.post("/api/chat/message", json={"message": "   "}).status_code == 422


def test_account_cannot_add_private_personalization_to_an_anonymous_link(api: Any) -> None:
    client, session = api
    anonymous = ChatSession(id=uuid4(), user_id=None)
    session.add(anonymous)
    app.dependency_overrides[chat_actor] = lambda: uuid4()
    result = client.post(
        "/api/chat/message", json={"session_id": str(anonymous.id), "message": "continue"}
    )
    assert result.status_code == 409
    assert session.messages == []


def test_intent_constraints_are_hard_filters() -> None:
    filters = _filters_from_intent(
        QueryIntent(
            runtime_max=90,
            genres_exclude=["Horror"],
            themes_exclude=["space"],
        )
    )
    assert filters.max_runtime == 90
    assert filters.excluded_genres == ["Horror"]
    assert filters.excluded_themes == ["space"]


def test_anonymous_chat_database_column_is_nullable() -> None:
    assert ChatSession.__table__.c.user_id.nullable is True


async def test_structured_exclusions_are_not_reparsed_as_positive_terms() -> None:
    session = Session()
    await catalog_search(
        session,
        "ignored raw query",
        SearchFilters(excluded_genres=["Horror"]),
        5,
        intent=QueryIntent(mood="cozy", themes_exclude=["space"], runtime_max=90),
    )  # type: ignore[arg-type]
    statement = session.statements[-1]
    sql = str(statement.compile(dialect=dialect()))
    assert "NOT" in sql and "movies.runtime" in sql and "movies.genres" in sql


async def test_openrouter_wire_format_and_json_mode() -> None:
    async def provider(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "openai/gpt-4.1-mini"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 1024
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"genres_include":["Comedy"]}'}}]}
        )

    client = ChatLLMClient(
        "test-only-key",
        model="openai/gpt-4.1-mini",
        base_url="https://openrouter.ai/api/v1",
        transport=httpx.MockTransport(provider),
    )
    try:
        intent = await client.complete_json(
            system_prompt="Return JSON", user_prompt="comedy", schema_model=QueryIntent
        )
        assert intent.genres_include == ["Comedy"]
    finally:
        await client.aclose()


async def test_free_router_strict_schema_and_no_reasoning() -> None:
    def provider(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "openrouter/free"
        assert payload["reasoning"] == {"enabled": False}
        response_format = payload["response_format"]
        assert response_format["type"] == "json_schema"
        schema = response_format["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = ChatLLMClient(
        "test-only-key",
        model="openrouter/free",
        base_url="https://openrouter.ai/api/v1",
        structured_outputs=True,
        disable_reasoning=True,
        transport=httpx.MockTransport(provider),
    )
    try:
        await client.complete_json(
            system_prompt="JSON", user_prompt="Comedy", schema_model=QueryIntent
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "body", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}]
)
async def test_malformed_provider_reply_is_a_controlled_failure(body: Any) -> None:
    client = ChatLLMClient(
        "test-only-key",
        model="test-model",
        base_url="https://provider.example/v1",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    try:
        with pytest.raises(LLMError):
            await client.complete_json(
                system_prompt="JSON", user_prompt="comedy", schema_model=QueryIntent
            )
    finally:
        await client.aclose()


async def test_tmdb_bundle_and_provider_errors_do_not_echo_credentials() -> None:
    def tmdb(request: httpx.Request) -> httpx.Response:
        assert request.url.params["append_to_response"] == "keywords"
        return httpx.Response(401, json={"status_message": "PRIVATE KEY ECHO"})

    async with TMDbClient("test-key", transport=httpx.MockTransport(tmdb)) as client:
        with pytest.raises(TMDbError) as error:
            await client.movie_bundle(157336)
    assert "PRIVATE" not in str(error.value)


async def test_refresh_preserves_personality_and_invalidates_stale_embedding() -> None:
    session = Session()
    await upsert_movie(session, {"tmdb_id": 1, "title": "Updated", "genres": [], "keywords": []})  # type: ignore[arg-type]
    sql = str(session.statements[-1].compile(dialect=dialect()))
    assert "coalesce(excluded.personality, movies.personality)" in sql
    assert "IS DISTINCT FROM" in sql
    assert "ELSE movies.embedding" in sql


def test_integration_status_exposes_only_configuration_flags(api: Any) -> None:
    client, _ = api
    status = client.get("/api/integrations")
    assert status.status_code == 200
    assert set(status.json()) == {"chat_configured", "tmdb_configured"}
    assert "https://" not in status.text
    assert "api_key" not in status.text
