"""Tests for the TMDb ingestion service (no network, no Postgres required)."""

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.services.ingestion import (
    IngestStats,
    TMDbClient,
    TMDbError,
    ingest_movies,
    movie_row_from_tmdb,
)

# --- Fixtures: representative TMDb payloads (also documents the API shape) ---


@pytest.fixture
def detail_payload() -> dict[str, Any]:
    return {
        "id": 157336,
        "title": "Interstellar",
        "original_title": "Interstellar",
        "overview": "The adventures of a group of explorers...",
        "release_date": "2014-11-05",
        "runtime": 169,
        "genres": [{"id": 878, "name": "Science Fiction"}, {"id": 12, "name": "Adventure"}],
        "original_language": "en",
        "poster_path": "/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
        "vote_average": 8.4,
        "vote_count": 34953,
        "popularity": 700.0,
    }


@pytest.fixture
def keywords_payload() -> dict[str, Any]:
    return {
        "keywords": [
            {"id": 290, "name": "space"},
            {"id": 10175, "name": "time travel"},
        ]
    }


# --- movie_row_from_tmdb -----------------------------------------------------


def test_movie_row_mapper(detail_payload: dict, keywords_payload: dict) -> None:
    row = movie_row_from_tmdb(detail_payload, keywords_payload)

    assert row["tmdb_id"] == 157336
    assert row["title"] == "Interstellar"
    assert row["release_year"] == 2014
    assert row["runtime"] == 169
    assert row["genres"] == ["Science Fiction", "Adventure"]
    assert row["keywords"] == ["space", "time travel"]
    assert row["language"] == "en"
    assert row["vote_average"] == pytest.approx(8.4)
    assert row["personality"] is None  # filled later by module 7


def test_movie_row_mapper_handles_sparse_payloads() -> None:
    row = movie_row_from_tmdb({"id": 42, "title": "X"}, {"keywords": None})
    assert row["release_year"] is None
    assert row["genres"] == []
    assert row["keywords"] == []
    assert row["overview"] is None
    assert row["runtime"] is None


def test_movie_row_mapper_falls_back_to_original_title() -> None:
    row = movie_row_from_tmdb({"id": 7, "original_title": "La Haine", "release_date": ""}, {})
    assert row["title"] == "La Haine"


# --- upsert_movie (SQL shape) -------------------------------------------------


def test_upsert_sql_conflicts_on_tmdb_id() -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import Movie

    statement = pg_insert(Movie).values(
        tmdb_id=1, title="T", genres=[], keywords=[], personality=None
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Movie.__table__.c.tmdb_id],
        set_={"title": statement.excluded.title},
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (tmdb_id) DO UPDATE" in sql


# --- TMDbClient backoff / error handling --------------------------------------


def _client_with_responses(responses: list[httpx.Response]) -> TMDbClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    return TMDbClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


def _patch_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace ingestion's asyncio.sleep with a recording no-op awaitable."""
    sleeps: list[float] = []

    class _Noop:
        def __init__(self, delay: float) -> None:
            self.delay = delay

        def __await__(self):  # awaitable that records and returns immediately
            sleeps.append(self.delay)

            async def _noop() -> None:
                return None

            return _noop().__await__()

    monkeypatch.setattr(
        "app.services.ingestion.asyncio.sleep", lambda delay: _Noop(delay)
    )
    return sleeps


def test_client_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A rate-limited call must retry (honoring Retry-After) and succeed."""
    sleeps = _patch_sleeps(monkeypatch)
    client = _client_with_responses(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"results": [{"id": 1}]}),
        ]
    )
    result = asyncio.run(client.discover_popular(1))
    asyncio.run(client.aclose())
    assert result == [{"id": 1}]
    assert len(sleeps) == 1


def test_client_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _patch_sleeps(monkeypatch)
    client = _client_with_responses([httpx.Response(500)] * 5)
    with pytest.raises(TMDbError):
        asyncio.run(client.discover_popular(1))
    asyncio.run(client.aclose())
    assert len(sleeps) == 5  # one backoff per failed attempt


def test_client_raises_for_permanent_client_error() -> None:
    client = _client_with_responses([httpx.Response(404, json={"status_message": "not found"})])
    with pytest.raises(TMDbError):
        asyncio.run(client.movie_detail(999999))
    asyncio.run(client.aclose())


def test_client_rejects_empty_api_key() -> None:
    with pytest.raises(TMDbError):
        TMDbClient(api_key="")


# --- ingest_movies end-to-end with fakes --------------------------------------


class FakeClient:
    """Fake TMDbClient: deterministic payloads, one poisoned movie."""

    def __init__(self, ids_by_page: dict[int, list[int]], poisoned_id: int) -> None:
        self.calls: list[str] = []
        self._ids_by_page = ids_by_page
        self._poisoned_id = poisoned_id

    def _calls(self, method: str) -> None:
        self.calls.append(method)

    async def discover_popular(self, page: int) -> list[dict[str, Any]]:
        self._calls("popular")
        return [{"id": i, "title": f"Movie {i}"} for i in self._ids_by_page[page]]

    async def top_rated(self, page: int) -> list[dict[str, Any]]:
        self._calls("top_rated")
        return []

    async def movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        self._calls("detail")
        if tmdb_id == self._poisoned_id:
            raise TMDbError("boom")
        return {
            "id": tmdb_id,
            "title": f"Movie {tmdb_id}",
            "release_date": "2020-01-01",
            "genres": [{"name": "Drama"}],
            "runtime": 100,
            "vote_average": 7.0,
            "vote_count": 10,
            "popularity": 50.0,
            "original_language": "en",
            "overview": "Test overview.",
        }

    async def movie_keywords(self, tmdb_id: int) -> dict[str, Any]:
        self._calls("keywords")
        if tmdb_id == self._poisoned_id:
            raise TMDbError("boom")
        return {"keywords": [{"name": "space"}]}

    async def aclose(self) -> None:
        self._calls("close")


class FakeSession:
    """Minimal async session recording upserts."""

    def __init__(self) -> None:
        self.executed: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> None:
        self.executed.append(stmt)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSessionmaker:
    def __init__(self) -> None:
        self.sessions: list[FakeSession] = []

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.mark.asyncio
async def test_ingest_movies_dedupes_upserts_and_skips_failures() -> None:
    fake_client = FakeClient(ids_by_page={1: [1, 2, 2, 3], 2: [3, 4]}, poisoned_id=3)
    fake_sessionmaker = FakeSessionmaker()

    stats = await ingest_movies(
        pages=2, client=fake_client, sessionmaker=fake_sessionmaker  # type: ignore[arg-type]
    )

    # Dedup: {1, 2, 2, 3} ∪ {3, 4} → 4 unique candidates.
    assert stats.discovered == 4
    # tmdb_id=3 is poisoned → detail raises → skipped, not fatal.
    assert stats.succeeded == 3
    assert stats.failed == 1
    assert stats.failed_ids == [3]
    # One committed session per successful upsert.
    assert len(fake_sessionmaker.sessions) == 3
    # The caller passed the client in, so ingest_movies must not close it.
    assert "close" not in fake_client.calls


def test_ingest_movies_rejects_zero_pages() -> None:
    with pytest.raises(ValueError):
        asyncio.run(ingest_movies(pages=0))  # type: ignore[arg-type]


def test_ingest_stats_defaults() -> None:
    stats = IngestStats()
    assert stats.succeeded == 0 and stats.failed == 0
