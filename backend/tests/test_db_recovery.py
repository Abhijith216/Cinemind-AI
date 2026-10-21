"""Connection retries happen before the handler, never after its side effects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core import db


async def test_unavailable_database_returns_controlled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SimpleNamespace(
        connection=AsyncMock(side_effect=TimeoutError()), rollback=AsyncMock()
    )
    monkeypatch.setattr(db, "get_engine", lambda: SimpleNamespace(dispose=AsyncMock()))
    with pytest.raises(HTTPException) as error:
        await db.ensure_database_connection(session)
    assert error.value.status_code == 503
    assert session.connection.await_count == 2


async def test_recovers_connection_before_yield(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(
        connection=AsyncMock(side_effect=[TimeoutError(), None]), rollback=AsyncMock()
    )
    dispose = AsyncMock()
    monkeypatch.setattr(db, "get_engine", lambda: SimpleNamespace(dispose=dispose))
    await db.ensure_database_connection(session)
    assert session.connection.await_count == 2
    session.rollback.assert_awaited_once()
    dispose.assert_awaited_once()


async def test_handler_failure_rolls_back_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(
        connection=AsyncMock(), close=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock()
    )
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(db, "get_sessionmaker", lambda: factory)
    dependency = db.get_db_session()
    await anext(dependency)
    with pytest.raises(TimeoutError):
        await dependency.athrow(TimeoutError())
    assert factory.call_count == 1
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.close.assert_awaited_once()
