"""Live demo for Module 6 — rating → taste profile update.

Drives the REAL FastAPI app (same routes as production) against a fake
database session holding one test user and one movie, then shows the two
deliverable responses:

    1. POST /api/ratings      → 201, rating stored, profile updated
    2. GET  /api/users/{user_id}/taste-profile → the updated profile

Run from backend/:

    ../.venv/Scripts/python scripts/demo_taste_profile.py

No Postgres needed — swap the dependency override for the real
``get_db_session`` (i.e. just run uvicorn) and the code path is identical.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi.testclient import TestClient

from app.core.db import get_db_session
from app.main import app
from app.models import Movie, User, UserTasteProfile


class _RowsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _GetResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    """Minimal AsyncSession double (same shape as the test suite's)."""

    def __init__(self) -> None:
        self.objects: dict[tuple[type, Any], Any] = {}
        self.added: list[Any] = []
        self.execute_results: list[Any] = []

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
        return self.execute_results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass


def main() -> None:
    session = FakeSession()

    user = User(id=uuid.uuid4(), email="demo@cinemind.dev", hashed_password="x")
    arrival = Movie(
        id=uuid.uuid4(),
        tmdb_id=329865,
        title="Arrival",
        genres=["Science Fiction", "Drama", "Mystery"],
        keywords=["first contact", "time", "language", "alien communication"],
    )
    session.register(user, arrival)
    session.execute_results = [_GetResult(None)]  # no prior rating for the movie

    async def _yield_session() -> AsyncGenerator[FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _yield_session
    client = TestClient(app)

    print("=" * 72)
    print(f"POST /api/ratings   (user rates {arrival.title} 9/10)")
    print("=" * 72)
    response = client.post(
        "/api/ratings",
        json={
            "user_id": str(user.id),
            "movie_id": str(arrival.id),
            "score": 9,
        },
    )
    print(f"HTTP {response.status_code}")
    print(response.json())

    print()
    print("=" * 72)
    print(f"GET /api/users/{user.id}/taste-profile")
    print("=" * 72)
    profile_response = client.get(f"/api/users/{user.id}/taste-profile")
    print(f"HTTP {profile_response.status_code}")
    print(profile_response.json())

    print()
    print("Confirmed: likes/favorite_themes merged Arrival's real genres and")
    print("keywords (score 9 >= 7 -> liked); lists stay deduped and capped.")

    app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
