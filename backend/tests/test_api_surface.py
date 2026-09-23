"""API-surface tests: every documented route exists + new-endpoint behavior."""

import datetime
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db_session
from app.core.security import decode_access_token
from app.main import app
from app.models import Movie, TasteSnapshot, User

# --- the documented route surface (the contract with the frontend) ------------------

DOCUMENTED_ROUTES = [
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/movies/{movie_id}"),
    ("POST", "/api/search/hybrid"),
    ("POST", "/api/chat/message"),
    ("GET", "/api/chat/sessions/{session_id}"),
    ("POST", "/api/ratings"),
    ("GET", "/api/users/{user_id}/taste-profile"),
    ("GET", "/api/users/{user_id}/taste-evolution"),
    ("GET", "/api/movies/{movie_id}/recommendation-graph"),
]


def test_documented_routes_are_all_registered() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    documented = {(method, path) for method, path in DOCUMENTED_ROUTES}
    registered = {
        (method.upper(), path)
        for path, methods in schema["paths"].items()
        for method in methods
        if path.startswith("/api/")
    }
    missing = documented - registered
    assert not missing, f"documented routes missing from the API: {sorted(missing)}"


def test_every_route_has_a_response_model() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            if method == "parameters":
                continue
            assert "responses" in operation and operation["responses"], (
                f"{method.upper()} {path} has no documented responses"
            )
            success = [
                code
                for code in operation["responses"]
                if code.startswith(("2", "3"))
            ]
            assert success, f"{method.upper()} {path} lacks a 2xx/3xx response"


# --- fakes ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class FakeSession:
    """get/execute/commit double; execute() dispatches on table name."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.objects: dict[tuple[type, Any], Any] = {}
        self.added: list[Any] = []
        self.rows = rows or []
        self.commits = 0

    def register(self, *objects: Any) -> None:
        for obj in objects:
            key = obj.id if hasattr(obj, "id") else obj.user_id
            self.objects[(type(obj), key)] = obj

    async def get(self, model: Any, key: Any) -> Any:
        found = self.objects.get((model, key))
        if found is not None:
            return found
        for obj in self.added:
            if isinstance(obj, model) and getattr(obj, "id", None) == key:
                return obj
        return None

    async def execute(self, statement: Any) -> FakeResult:
        sql = str(statement)
        if "ratings" in sql:
            return FakeResult(self.rows)
        if "taste_snapshots" in sql:
            snapshots = [
                obj for obj in self.objects.values() if isinstance(obj, TasteSnapshot)
            ]
            return FakeResult(sorted(snapshots, key=lambda row: row.month))
        if "users" in sql:
            return FakeResult(
                [obj for obj in self.objects.values() if isinstance(obj, User)]
            )
        return FakeResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        # Mirror a real flush: column defaults (e.g. id=uuid4) fire on commit.
        from app.models import Base

        for obj in self.added:
            if isinstance(obj, Base) and getattr(obj, "id", "missing") is None:
                obj.id = uuid.uuid4()
        self.commits += 1

    async def refresh(self, obj: Any) -> None:
        # Stand in for the DB server defaults filling in on refresh.
        if getattr(obj, "created_at", "missing") is None:
            obj.created_at = datetime.datetime.now(datetime.UTC)


class FakeSessionmaker:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


def _override(session: FakeSession) -> None:
    async def _yield_session() -> AsyncGenerator[FakeSession, None]:
        yield session

    app.dependency_overrides[get_db_session] = _yield_session


@pytest.fixture
def api() -> Any:
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _movie(**kwargs: Any) -> Movie:
    return Movie(
        id=uuid.uuid4(),
        tmdb_id=kwargs.pop("tmdb_id", 1),
        title=kwargs.pop("title", "Arrival"),
        overview="First contact drama.",
        release_year=2016,
        runtime=116,
        genres=kwargs.pop("genres", ["Science Fiction", "Drama"]),
        keywords=kwargs.pop("keywords", ["time", "language"]),
        language="en",
        vote_average=8.0,
        vote_count=2000,
        popularity=90.0,
    )


# --- auth ------------------------------------------------------------------------------


def test_register_login_flow_issues_valid_jwt(api: Any) -> None:
    session = FakeSession()
    _override(session)

    registered = api.post(
        "/api/auth/register",
        json={"email": "demo@cinemind.dev", "password": "correct horse battery"},
    )
    assert registered.status_code == 201
    body = registered.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "demo@cinemind.dev"
    assert decode_access_token(body["access_token"]) == uuid.UUID(body["user"]["id"])

    # Login returns a valid token for the same user.
    session.register(session.added[0])
    logged_in = api.post(
        "/api/auth/login",
        json={"email": "demo@cinemind.dev", "password": "correct horse battery"},
    )
    assert logged_in.status_code == 200
    assert (
        decode_access_token(logged_in.json()["access_token"])
        == uuid.UUID(body["user"]["id"])
    )

    # Wrong password → 401 (the fake returns the user; verification fails).
    wrong = api.post(
        "/api/auth/login",
        json={"email": "demo@cinemind.dev", "password": "not-the-password"},
    )
    assert wrong.status_code == 401


def test_register_rejects_duplicate_email_and_weak_password(api: Any) -> None:
    session = FakeSession()
    existing = User(
        id=uuid.uuid4(),
        email="taken@cinemind.dev",
        hashed_password="x",
        created_at=datetime.datetime.now(datetime.UTC),
    )
    session.register(existing)
    _override(session)

    duplicate = api.post(
        "/api/auth/register",
        json={"email": "taken@cinemind.dev", "password": "long-enough-password"},
    )
    assert duplicate.status_code == 409

    weak = api.post(
        "/api/auth/register",
        json={"email": "new@cinemind.dev", "password": "short"},
    )
    assert weak.status_code == 422


def test_passwords_are_never_stored_plaintext(api: Any) -> None:
    session = FakeSession()
    _override(session)
    api.post(
        "/api/auth/register",
        json={"email": "hash@cinemind.dev", "password": "very secret phrase"},
    )
    stored = session.added[0].hashed_password
    assert "very secret phrase" not in stored
    assert stored.startswith("pbkdf2_sha256$")


# --- movies + recommendation graph --------------------------------------------------------


def test_get_movie_endpoint(api: Any) -> None:
    movie = _movie()
    session = FakeSession()
    session.register(movie)
    _override(session)

    found = api.get(f"/api/movies/{movie.id}")
    assert found.status_code == 200
    assert found.json()["title"] == "Arrival"

    missing = api.get(f"/api/movies/{uuid.uuid4()}")
    assert missing.status_code == 404


def test_recommendation_graph_grounds_in_rated_movies(api: Any) -> None:
    arrival = _movie(keywords=["time", "language"])
    interstellar = _movie(
        tmdb_id=2,
        title="Interstellar",
        genres=["Science Fiction", "Adventure"],
        keywords=["time", "space"],
    )
    rated_row = (interstellar, 10)
    session = FakeSession(rows=[rated_row])
    session.register(arrival, interstellar)
    _override(session)

    graph = api.get(
        f"/api/movies/{arrival.id}/recommendation-graph",
        params={"user_id": str(uuid.uuid4())},
    )
    assert graph.status_code == 200
    body = graph.json()
    assert body["movie"]["title"] == "Arrival"
    assert [node["title"] for node in body["rated_movies"]] == ["Interstellar"]
    assert body["edges"][0]["shared_genres"] == ["Science Fiction"]
    assert body["edges"][0]["shared_keywords"] == ["time"]
    assert body["note"] is None


def test_recommendation_graph_notes_missing_grounding(api: Any) -> None:
    movie = _movie()
    session = FakeSession()
    session.register(movie)
    _override(session)

    anonymous = api.get(f"/api/movies/{movie.id}/recommendation-graph")
    assert anonymous.status_code == 200
    assert anonymous.json()["note"]  # explains why the graph is not grounded

    rated_none = api.get(
        f"/api/movies/{movie.id}/recommendation-graph",
        params={"user_id": str(uuid.uuid4())},
    )
    assert "not rated any movies" in rated_none.json()["note"]


# --- users: taste evolution ------------------------------------------------------------------


def test_taste_evolution_returns_sorted_snapshots(api: Any) -> None:
    user = User(
        id=uuid.uuid4(), email="evo@cinemind.dev", hashed_password="x",
        created_at=datetime.datetime.now(datetime.UTC),
    )
    snapshots = [
        TasteSnapshot(
            id=uuid.uuid4(),
            user_id=user.id, month="2026-08",
            dominant_genres=["Comedy"], dominant_themes=["pranks"],
        ),
        TasteSnapshot(
            id=uuid.uuid4(),
            user_id=user.id, month="2026-09",
            dominant_genres=["Science Fiction"], dominant_themes=["time"],
        ),
    ]
    session = FakeSession()
    session.register(user, *snapshots)
    _override(session)

    evolution = api.get(f"/api/users/{user.id}/taste-evolution")
    assert evolution.status_code == 200
    months = [row["month"] for row in evolution.json()]
    assert months == ["2026-08", "2026-09"]

    missing_user = api.get(f"/api/users/{uuid.uuid4()}/taste-evolution")
    assert missing_user.status_code == 404


# --- chat session replay ------------------------------------------------------------------------


def test_chat_session_endpoint_404_for_unknown_session(api: Any) -> None:
    _override(FakeSession())
    response = api.get(f"/api/chat/sessions/{uuid.uuid4()}")
    assert response.status_code == 404
