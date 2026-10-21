"""Catalog refresh checkpoints, filtering, credentials and SQL preservation."""

import argparse
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from app.services import catalog_refresh as catalog
from app.services.ingestion import TMDbClient, TMDbError, movie_row_from_tmdb, upsert_movies


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ({"release_date": "2025-01-01"}, True),
        ({"release_date": "2027-01-01"}, False),
        ({"release_date": "2025-01-01", "adult": True}, False),
        ({"release_date": "garbage"}, False),
        ({}, False),
    ],
)
def test_only_released_nonadult_discoveries(detail: dict, expected: bool) -> None:
    assert catalog.eligible_release(detail, date(2026, 10, 21)) is expected


async def test_recent_discovery_bounds_and_combined_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    async with TMDbClient("test", transport=httpx.MockTransport(handler)) as client:
        await client.released_movies(2, since=date(2024, 1, 1))
        await client.movie_bundle(42)
    params = requests[0].url.params
    assert params["primary_release_date.gte"] == "2024-01-01"
    assert params["primary_release_date.lte"] == date.today().isoformat()
    assert params["include_adult"] == "false"
    assert requests[1].url.params["append_to_response"] == "keywords"


async def test_batch_is_bounded_and_isolates_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    active = maximum = 0

    async def bundle(movie_id: int) -> dict:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        if movie_id == 2:
            raise TMDbError("Missing", status_code=404)
        if movie_id == 3:
            raise TMDbError("Network failed")
        return {"id": movie_id, "title": "Film", "release_date": "2024-01-01"}

    client = SimpleNamespace(movie_bundle=bundle)
    report = catalog.RefreshReport()
    rows = await catalog.fetch_batch(client, list(range(1, 11)), set(), report)
    assert maximum <= catalog.FETCH_CONCURRENCY
    assert len(rows) == 8
    assert report.unavailable == [2]
    assert report.failed == [3]
    assert all(row["tmdb_synced_at"] is not None for row in rows)


async def test_invalid_credentials_abort_instead_of_checkpointing() -> None:
    client = SimpleNamespace(
        movie_bundle=AsyncMock(side_effect=TMDbError("Denied", status_code=401))
    )
    report = catalog.RefreshReport()
    with pytest.raises(TMDbError):
        await catalog.fetch_batch(client, [1], set(), report)
    assert report.failed == []
    assert report.unavailable == []


async def test_bulk_upsert_preserves_identity_and_derived_data() -> None:
    session = SimpleNamespace(execute=AsyncMock())
    rows = [movie_row_from_tmdb({"id": i, "title": "Film"}, {}) for i in (1, 2)]
    await upsert_movies(session, rows)
    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    update_sql = sql.split("DO UPDATE SET", 1)[1]
    assert "id =" not in update_sql
    assert "created_at =" not in update_sql
    assert "coalesce(excluded.personality, movies.personality)" in update_sql
    assert "ELSE movies.embedding END" in update_sql
    assert "tmdb_synced_at =" in update_sql
    assert len(statement.compile().params) > 20  # two rows, one network/database statement


async def test_checkpoints_commit_with_metadata_or_not_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(catalog, "get_sessionmaker", lambda: lambda: context)
    upsert = AsyncMock()
    monkeypatch.setattr(catalog, "upsert_movies", upsert)
    await catalog.save_batch([], [1, 2])
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.commit.reset_mock()
    upsert.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await catalog.save_batch([], [3])
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("args", [{"limit": 0}, {"pages": 51}, {"stale_days": 0}])
async def test_invalid_bounds_do_not_start_work(args: dict) -> None:
    with pytest.raises(ValueError):
        await catalog.refresh_catalog(**args)


async def test_resume_skips_fresh_rows_and_deduplicates_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [1, 2]
    stale_result = MagicMock()
    stale_result.scalars.return_value.all.return_value = [2]
    session = SimpleNamespace(execute=AsyncMock(side_effect=[existing_result, stale_result]))
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=session)
    db_context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(catalog, "get_sessionmaker", lambda: lambda: db_context)
    items = [{"id": i, "release_date": "2024-01-01"} for i in (1, 2, 3)]
    client = SimpleNamespace(
        released_movies=AsyncMock(return_value=items), top_rated=AsyncMock(return_value=items)
    )
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(catalog, "TMDbClient", lambda *_: client_context)
    fetch = AsyncMock(return_value=[{"tmdb_id": 3}, {"tmdb_id": 2}])
    save = AsyncMock()
    monkeypatch.setattr(catalog, "fetch_batch", fetch)
    monkeypatch.setattr(catalog, "save_batch", save)
    monkeypatch.setattr(catalog, "dispose_engine", AsyncMock())
    report = await catalog.refresh_catalog(limit=5, pages=1)
    assert fetch.call_args.args[1] == [3, 2]  # fresh 1 skipped; 2 and 3 fetched once each
    assert report.selected == report.updated == 2
    sql = str(session.execute.call_args_list[1].args[0].compile())
    assert "movies.tmdb_checked_at IS NULL" in sql
    assert "movies.tmdb_checked_at <" in sql
    # Simulate restart after successful commit: all three rows are now fresh.
    existing_result.scalars.return_value.all.return_value = [1, 2, 3]
    stale_result.scalars.return_value.all.return_value = []
    session.execute.side_effect = [existing_result, stale_result]
    fetch.reset_mock()
    report = await catalog.refresh_catalog(limit=5, pages=1)
    assert report.selected == report.updated == 0
    fetch.assert_not_awaited()


async def test_aborted_run_reports_failure_without_leaking_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        catalog, "refresh_catalog", AsyncMock(side_effect=RuntimeError("secret credential"))
    )
    args = argparse.Namespace(limit=10, pages=1, stale_days=7, interval_hours=0)
    assert await catalog.run(args) == 1
    assert "secret credential" not in caplog.text
    assert "committed batches are retained" in caplog.text


async def test_daily_worker_waits_between_completed_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    refresh = AsyncMock(return_value=catalog.RefreshReport(finished_at="finished"))
    sleep = AsyncMock(side_effect=asyncio.CancelledError())
    monkeypatch.setattr(catalog, "refresh_catalog", refresh)
    monkeypatch.setattr(catalog.asyncio, "sleep", sleep)
    args = argparse.Namespace(limit=1000, pages=10, stale_days=7, interval_hours=24)
    with pytest.raises(asyncio.CancelledError):
        await catalog.run(args)
    refresh.assert_awaited_once_with(limit=1000, pages=10, stale_days=7)
    sleep.assert_awaited_once_with(86400)
