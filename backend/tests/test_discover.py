"""Discover regressions: real contract, metadata queries and failure recovery."""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql.asyncpg import dialect
from sqlalchemy.exc import OperationalError

from app.core.db import get_db_session
from app.core.rate_limit import reset_all_limiters
from app.main import app
from app.models import Movie
from app.schemas.retrieval import SearchFilters
from app.services.catalog_search import catalog_search, parse_catalog_query
from app.services.starter_catalog import parse_starter_row


def test_reference_exclusion_and_duration() -> None:
    parsed = parse_catalog_query("Something like Interstellar but not about space")
    assert parsed.reference_title == "interstellar"
    assert parsed.excluded == ["space"]
    assert "interstellar" not in parsed.terms
    parsed = parse_catalog_query("Mind-bending, emotional, under two hours")
    assert parsed.max_runtime == 119
    assert "dream" in parsed.terms
    assert "drama" in parsed.terms
    assert not set(parsed.terms) & {"under", "hours", "two"}


@pytest.mark.parametrize(
    "query, expected",
    [
        ("comedy under 90 minutes", 89),
        ("thriller less than 2 hours", 119),
        ("a cozy movie", None),
    ],
)
def test_runtime_parsing(query: str, expected: int | None) -> None:
    assert parse_catalog_query(query).max_runtime == expected


def test_exclusions_apply_aliases_and_keep_positive_terms() -> None:
    parsed = parse_catalog_query("funny, no scary movies")
    assert "comedy" in parsed.terms
    assert "horror" in parsed.excluded
    assert "horror" not in parsed.terms


def test_duration_after_reference_and_exclusion() -> None:
    parsed = parse_catalog_query("like Interstellar under two hours")
    assert parsed.reference_title == "interstellar"
    assert parsed.max_runtime == 119
    parsed = parse_catalog_query("no horror under 90 minutes")
    assert parsed.excluded == ["horror"]
    assert parsed.max_runtime == 89


class Result:
    def __init__(self, rows: list[Movie]) -> None:
        self.rows = rows

    def scalars(self) -> "Result":
        return self

    def all(self) -> list[Movie]:
        return self.rows

    def scalar_one_or_none(self) -> Movie | None:
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, rows: list[Movie] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> Result:
        self.statements.append(statement)
        return Result(self.rows)


@pytest.fixture
def client(monkeypatch: Any) -> Any:
    reset_all_limiters()

    async def session() -> AsyncGenerator[Session, None]:
        yield Session()

    app.dependency_overrides[get_db_session] = session

    async def no_external_lookup(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("app.api.search.resolve_references", no_external_lookup)
    monkeypatch.setattr("app.api.search.ensure_database_connection", no_external_lookup)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        reset_all_limiters()


@pytest.mark.parametrize("query", ["", "   ", "\n\t", "x" * 1001])
def test_rejects_empty_or_oversized_queries(client: TestClient, query: str) -> None:
    assert client.post("/api/search/discover", json={"query": query}).status_code == 422


def test_invalid_year_range_and_runtime(client: TestClient) -> None:
    for filters in [
        {"min_release_year": 2020, "max_release_year": 2000},
        {"max_runtime": 0},
    ]:
        assert (
            client.post(
                "/api/search/discover",
                json={
                    "query": "comedy",
                    "filters": filters,
                },
            ).status_code
            == 422
        )


def test_catalog_needs_no_embedding_provider(client: TestClient, monkeypatch: Any) -> None:
    async def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Discover must not call the embedding provider")

    monkeypatch.setattr("app.api.search.embed_query", forbidden)
    response = client.post("/api/search/discover", json={"query": "comedy"})
    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["search_mode"] == "catalog"


def test_database_failure_has_safe_retryable_error(client: TestClient, monkeypatch: Any) -> None:
    async def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise OperationalError("PRIVATE CONNECTION STRING", {}, Exception("PRIVATE CREDENTIAL"))

    monkeypatch.setattr("app.api.search.catalog_search", unavailable)
    response = client.post("/api/search/discover", json={"query": "comedy"})
    assert response.status_code == 503
    assert "try again" in response.json()["detail"].lower()
    assert "PRIVATE" not in response.text


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://127.0.0.1:3000"])
def test_browser_preflight_allows_both_local_hosts(client: TestClient, origin: str) -> None:
    response = client.options(
        "/api/search/discover",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_catalog_query_and_grounded_result() -> None:
    movie = Movie(
        id=uuid4(),
        tmdb_id=1,
        title="A Comedy",
        genres=["Comedy"],
        keywords=["friendship"],
        runtime=88,
    )
    session = Session([movie])
    results = await catalog_search(
        session,
        "cozy under two hours, no horror",  # type: ignore[arg-type]
        SearchFilters(
            genres=["Comedy"],
            max_runtime=90,
            min_rating=6,
            languages=["en"],
            min_release_year=1990,
            max_release_year=2016,
        ),
        12,
    )
    assert results[0].movie.id == movie.id
    assert "Comedy" in results[0].matched_terms
    assert "88 minutes" in results[0].explanation
    sql = str(session.statements[0].compile(dialect=dialect()))
    # regconfig and weight literals must not be sent as VARCHAR parameters.
    assert "'english'::regconfig" in sql
    assert "movies.search_document @@" in sql
    from app.core.search_document import SEARCH_DOCUMENT_SQL

    assert "'A'" in SEARCH_DOCUMENT_SQL
    for column in ["runtime", "language", "release_year", "vote_average", "genres"]:
        assert f"movies.{column}" in sql
    assert "NOT" in sql
    assert "LIMIT" in sql


async def test_unknown_reference_does_not_return_random_movies() -> None:
    session = Session()
    results = await catalog_search(
        session,
        "like a completely unknown film",
        SearchFilters(),
        12,  # type: ignore[arg-type]
    )
    assert results == []
    assert len(session.statements) == 1


async def test_genre_filter_does_not_broaden_unmatched_query() -> None:
    session = Session()
    await catalog_search(
        session,
        "zzzzunmatchablecatalogquery",  # type: ignore[arg-type]
        SearchFilters(genres=["Comedy"]),
        12,
    )
    params = session.statements[0].compile(dialect=dialect()).params.values()
    assert "zzzzunmatchablecatalogquery" in params
    assert "zzzzunmatchablecatalogquery OR comedy" not in params


async def test_exclusion_only_request_searches_catalog() -> None:
    session = Session()
    await catalog_search(session, "no horror", SearchFilters(), 12)  # type: ignore[arg-type]
    assert len(session.statements) == 1
    assert "NOT" in str(session.statements[0])


def test_starter_import_preserves_source_values_and_missing_fields() -> None:
    row = parse_starter_row(
        {
            "id": "157336",
            "title": "Interstellar",
            "release_date": "2014-11-05",
            "runtime": "169.0",
            "genres": '[{"name":"Science Fiction"}]',
            "keywords": '[{"name":"space travel"}]',
            "vote_average": "8.1",
        }
    )
    assert row["tmdb_id"] == 157336
    assert row["runtime"] == 169
    assert row["genres"] == ["Science Fiction"]
    assert row["overview"] is None
    assert "poster_path" not in row
    assert "embedding" not in row
