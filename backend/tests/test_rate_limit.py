"""Tests for the LLM-route rate limiter (offline, no network/DB)."""

from collections.abc import AsyncGenerator
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.rate_limit import RateLimiter, reset_all_limiters
from app.main import app


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeSession:
    async def get(self, model: Any, key: Any) -> Any:
        return None

    async def execute(self, statement: Any) -> _FakeResult:
        return _FakeResult([])

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass


async def _yield_fake_session() -> AsyncGenerator[_FakeSession, None]:
    yield _FakeSession()


class _EmbeddingPayload(BaseModel):
    input: list[str]
    model: str


def test_disabled_limiter_never_blocks() -> None:
    limiter = RateLimiter("chat", 0)
    assert not limiter.enabled
    for _ in range(100):
        assert limiter.check("host:test") == 0


def test_limiter_blocks_after_limit_and_reports_retry_after() -> None:
    limiter = RateLimiter("search", 2)
    assert limiter.check("host:test") == 0
    assert limiter.check("host:test") == 0
    retry_after = limiter.check("host:test")
    assert retry_after > 0
    assert retry_after <= 61


def test_limiter_keys_are_independent() -> None:
    limiter = RateLimiter("chat", 1)
    assert limiter.check("host:a") == 0
    assert limiter.check("host:a") > 0
    assert limiter.check("host:b") == 0


def _set_limits(chat: int, search: int) -> None:
    settings = get_settings()
    settings.chat_rate_limit_per_minute = chat
    settings.search_rate_limit_per_minute = search


async def _instant_backoff(_attempt: int, _retry_after: str | None = None) -> None:
    """Replace the LLM client's retry backoff so unreachable-provider tests
    fail fast instead of sleeping through exponential retries."""


def test_endpoints_return_429_with_retry_after(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")  # nothing listens
    monkeypatch.setattr("app.services.llm_client._sleep_backoff", _instant_backoff)
    monkeypatch.setattr("app.services.embeddings._sleep_backoff", _instant_backoff)
    get_settings.cache_clear()
    reset_all_limiters()  # other tests may have consumed slots under this client key
    app.dependency_overrides[get_db_session] = _yield_fake_session

    try:
        _set_limits(chat=1, search=1)
        client = TestClient(app)

        first = client.post("/api/chat/message", json={"message": "hi"})
        assert first.status_code == 503, first.text  # provider unreachable → 503, not a crash
        second = client.post("/api/chat/message", json={"message": "hi again"})
        assert second.status_code == 429, second.text
        assert "Retry-After" in second.headers
        assert "Rate limit exceeded" in second.json()["detail"]

        search_first = client.post("/api/search/hybrid", json={"query": "warm comedies"})
        assert search_first.status_code == 503, search_first.text
        search_second = client.post("/api/search/hybrid", json={"query": "warm comedies"})
        assert search_second.status_code == 429
    finally:
        _set_limits(chat=0, search=0)
        get_settings.cache_clear()
        app.dependency_overrides.pop(get_db_session, None)


def test_zero_limit_disables_limiting_on_endpoints(monkeypatch) -> None:
    app.dependency_overrides[get_db_session] = _yield_fake_session

    try:
        _set_limits(chat=0, search=0)
        client = TestClient(app)
        for _ in range(3):
            response = client.post("/api/search/hybrid", json={"query": "x"})
            assert response.status_code != 429
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        get_settings.cache_clear()
