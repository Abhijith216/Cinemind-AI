"""A refresh survives transient database disconnects without duplicating writes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import tmdb_sync


@pytest.mark.parametrize("recover", [True, False])
async def test_refresh_retries_a_failed_transaction(
    monkeypatch: pytest.MonkeyPatch, recover: bool
) -> None:
    session = SimpleNamespace(commit=AsyncMock())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(tmdb_sync, "get_sessionmaker", lambda: factory)
    write = AsyncMock(side_effect=[TimeoutError(), None if recover else TimeoutError()])
    monkeypatch.setattr(tmdb_sync, "upsert_movie", write)
    dispose = AsyncMock()
    monkeypatch.setattr(tmdb_sync, "dispose_engine", dispose)
    monkeypatch.setattr(tmdb_sync.asyncio, "sleep", AsyncMock())
    row = {"tmdb_id": 157336, "title": "Interstellar"}
    if recover:
        await tmdb_sync._save_refreshed_movie(row)
        session.commit.assert_awaited_once()
    else:
        with pytest.raises(TimeoutError):
            await tmdb_sync._save_refreshed_movie(row)
        session.commit.assert_not_awaited()
    assert write.await_count == 2
    assert dispose.await_count == (1 if recover else 2)
