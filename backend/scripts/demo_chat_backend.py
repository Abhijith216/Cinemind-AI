"""Long-running local CineMind backend for frontend E2E work.

Runs the REAL FastAPI app (real orchestrator, parse_query, hybrid retrieval,
grounded explanations, graph builder, taste endpoints) with two offline
seams — the same ones as ``demo_chat.py``:

- a local OpenAI-compatible server plays the chat model AND embeddings;
- a SQL-dispatching fake session stands in for Postgres.

This variant seeds a TEST USER with backdated ratings and monthly taste
snapshots, so the visual features have real data:

- ``GET /api/users/{id}/taste-evolution``  -> 4 monthly snapshots
  (Action/Adventure -> Thriller/Mystery -> Drama/Romance -> Sci-Fi/Drama)
- ``GET /api/movies/{arrival_id}/recommendation-graph?user_id={id}``
  -> edges with concrete shared genres/keywords to the loved movies
- ``POST /api/chat/message`` with ``user_id`` -> explanations cite the
  user's actual loved movies

Run from backend/:

    ../.venv/Scripts/python scripts/demo_chat_backend.py

and open the printed frontend URLs.
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.db import get_db_session
from app.main import app
from app.models import ChatMessage, Movie, Rating, TasteSnapshot, User

MOCK_PORT = 8953
API_PORT = 8000

DEMO_USER_ID = uuid.UUID("00000000-0000-4000-8000-c1e0deadbeef")


# --- seeded catalog (the fake Postgres) -----------------------------------------------


def seed_movies() -> list[Movie]:
    """Catalog with real overlaps: loved movies, recommendation targets, filler."""

    def movie(index: int, **fields: Any) -> Movie:
        defaults: dict[str, Any] = {
            "id": uuid.uuid4(),
            "tmdb_id": 600000 + index,
            "language": "en",
            "vote_average": 8.0,
            "vote_count": 3000,
            "popularity": 90.0 + index,
        }
        defaults.update(fields)
        return Movie(**defaults)

    return [
        # Loved movies (rated 8+)
        movie(
            1,
            title="Interstellar",
            overview="A team of explorers travel through a wormhole in space.",
            release_year=2014,
            runtime=169,
            genres=["Science Fiction", "Drama", "Adventure"],
            keywords=["time", "space", "father-daughter", "survival"],
            personality={
                "emotion": 90, "mind_blowing": 95, "darkness": 55, "humor": 20,
                "violence": 30, "romance": 35, "hopefulness": 60,
                "plot_complexity": 90, "rewatchability": 80,
            },
        ),
        movie(
            2,
            title="Blade Runner 2049",
            overview="A young blade runner discovers a long-buried secret.",
            release_year=2017,
            runtime=164,
            genres=["Science Fiction", "Drama", "Mystery"],
            keywords=["time", "identity", "dystopia", "mind-bending"],
            personality={
                "emotion": 80, "mind_blowing": 90, "darkness": 70, "humor": 10,
                "violence": 45, "romance": 30, "hopefulness": 40,
                "plot_complexity": 85, "rewatchability": 75,
            },
        ),
        movie(
            3,
            title="Memento",
            overview="A man with short-term memory loss hunts his wife's killer.",
            release_year=2000,
            runtime=113,
            genres=["Thriller", "Mystery", "Drama"],
            keywords=["memory", "mind-bending", "identity", "revenge"],
            personality={
                "emotion": 75, "mind_blowing": 92, "darkness": 75, "humor": 10,
                "violence": 55, "romance": 20, "hopefulness": 25,
                "plot_complexity": 95, "rewatchability": 85,
            },
        ),
        movie(
            4,
            title="Divergent",
            overview="A teen must choose a faction in a divided society.",
            release_year=2014,
            runtime=139,
            genres=["Action", "Adventure", "Romance"],
            keywords=["dystopia", "chosen one", "teen"],
            personality={
                "emotion": 60, "mind_blowing": 30, "darkness": 45, "humor": 25,
                "violence": 55, "romance": 60, "hopefulness": 65,
                "plot_complexity": 40, "rewatchability": 35,
            },
        ),
        # Recommendation targets
        movie(
            5,
            title="Arrival",
            overview="A linguist works with the military to contact alien life.",
            release_year=2016,
            runtime=116,
            genres=["Science Fiction", "Drama", "Mystery"],
            keywords=["time", "first contact", "language", "mind-bending"],
            personality={
                "emotion": 85, "mind_blowing": 88, "darkness": 45, "humor": 15,
                "violence": 20, "romance": 25, "hopefulness": 55,
                "plot_complexity": 82, "rewatchability": 70,
            },
        ),
        # Chat-search filler (Wormhole Protocol 1-4 style)
        movie(
            6,
            title="Wormhole Protocol 4",
            overview="A tense, mind-bending science fiction puzzle.",
            release_year=2018,
            runtime=118,
            genres=["Science Fiction", "Drama"],
            keywords=["time", "mind-bending", "puzzle"],
            personality={
                "emotion": 80, "mind_blowing": 90, "darkness": 40, "humor": 20,
                "violence": 25, "romance": 25, "hopefulness": 55,
                "plot_complexity": 85, "rewatchability": 75,
            },
        ),
        movie(
            7,
            title="Wormhole Protocol 3",
            overview="A tense, mind-bending science fiction puzzle.",
            release_year=2017,
            runtime=118,
            genres=["Science Fiction", "Drama"],
            keywords=["time", "mind-bending", "puzzle"],
            personality={
                "emotion": 78, "mind_blowing": 88, "darkness": 42, "humor": 20,
                "violence": 25, "romance": 25, "hopefulness": 55,
                "plot_complexity": 84, "rewatchability": 74,
            },
        ),
    ]


def movie_by_title(movies: list[Movie], title: str) -> Movie:
    return next(m for m in movies if m.title == title)


def seed_ratings(movies: list[Movie]) -> list[Rating]:
    """Backdated ratings for the demo user (loved: Interstellar/BR2049/Memento)."""

    def rating(movie_title: str, score: int, iso: str) -> Rating:
        return Rating(
            user_id=DEMO_USER_ID,
            movie_id=movie_by_title(movies, movie_title).id,
            score=score,
            rated_at=datetime.fromisoformat(iso),
        )

    return [
        rating("Memento", 9, "2026-08-20T21:00:00+00:00"),
        rating("Interstellar", 10, "2026-09-01T20:00:00+00:00"),
        rating("Blade Runner 2049", 9, "2026-09-05T20:30:00+00:00"),
        rating("Divergent", 3, "2026-09-08T19:00:00+00:00"),
    ]


def seed_snapshots() -> list[TasteSnapshot]:
    """Monthly dominant tags — the 'Action -> Thrillers -> Drama' arc."""
    months = [
        ("2026-06", ["Action", "Adventure"], ["space", "survival"]),
        ("2026-07", ["Thriller", "Action"], ["survival", "mind-bending"]),
        ("2026-08", ["Thriller", "Mystery", "Drama"], ["mind-bending", "identity"]),
        ("2026-09", ["Science Fiction", "Thriller", "Drama"], ["time", "mind-bending"]),
    ]
    return [
        TasteSnapshot(
            user_id=DEMO_USER_ID,
            month=month,
            dominant_genres=genres,
            dominant_themes=themes,
        )
        for month, genres, themes in months
    ]


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class DispatchingFakeSession:
    """Postgres stand-in that routes each statement by its distinctive SQL.

    Routes (checked in order):
    - ``<=>``               -> cosine candidates: (movie, distance) rows
    - ``movies.personality``-> user history vector: (personality,) rows
    - ``rated_at``          -> month-window ratings: [] (snapshots pre-seeded)
    - ``taste_snapshots``   -> the seeded snapshot rows, ordered by month
    - ``chat_messages``     -> persisted chat turns, ordered by created_at
    - ``score >=``          -> loved (8+) rows: (movie, score)
    - ``DESC``              -> top-rated rows for the graph: (movie, score)
    - plain ``ratings``     -> no existing rating (scalar_one_or_none -> None)
    """

    def __init__(
        self,
        movies: list[Movie],
        ratings: list[Rating],
        snapshots: list[TasteSnapshot],
        user: User,
    ) -> None:
        self.movies = movies
        self.ratings = ratings
        self.snapshots = sorted(snapshots, key=lambda row: row.month)
        self.user = user
        self.static: dict[type[Any], Any] = {User: user}
        self.added: list[Any] = []

    async def get(self, model: Any, key: Any) -> Any:
        for obj in self.added:
            if isinstance(obj, model) and getattr(obj, "id", None) == key:
                return obj
        if model is User and key == self.user.id:
            return self.user
        for obj in [*self.movies, *self.ratings, *self.snapshots]:
            if isinstance(obj, model) and getattr(obj, "id", None) == key:
                return obj
        return None

    def _loved_rows(self) -> list[tuple[Movie, int]]:
        loved = [
            (rating.movie_id, rating.score)
            for rating in self.ratings
            if rating.score >= 8
        ]
        scores = dict(loved)
        rows = [
            (movie, scores[movie.id])
            for movie in self.movies
            if movie.id in scores
        ]
        rows.sort(key=lambda pair: pair[1], reverse=True)
        return rows

    async def execute(self, statement: Any) -> FakeResult:
        sql = str(statement)
        if "<=>" in sql:
            distances = [0.90, 0.85, 0.82, 0.78, 0.74, 0.70, 0.66]
            return FakeResult(list(zip(self.movies, distances, strict=True)))
        if "rated_at" in sql:
            return FakeResult([])  # month windows: snapshots are pre-seeded
        if "taste_snapshots" in sql:
            return FakeResult(self.snapshots)
        if "chat_messages" in sql:
            messages = [obj for obj in self.added if isinstance(obj, ChatMessage)]
            messages.sort(key=lambda message: message.created_at)
            return FakeResult(messages)
        if "movies.personality" in sql and sql.lower().startswith(
            "select movies.personality"
        ):
            # History vector: one (personality,) row per loved movie.
            return FakeResult(
                [(movie.personality,) for movie, _ in self._loved_rows()]
            )
        if ">=" in sql:
            # Loved (8+) rows: (movie, score) — explain's taste grounding.
            return FakeResult(self._loved_rows())
        if "DESC" in sql:
            # Top-rated rows: (movie, score) — the graph's rated movies.
            return FakeResult(self._loved_rows()[:5])
        if "ratings" in sql:
            return FakeResult([])  # existing-rating lookup: none yet
        return FakeResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass


# --- mock OpenAI-compatible server ----------------------------------------------------


class _MockChatMessage(BaseModel):
    role: str
    content: str


class _MockChatRequest(BaseModel):
    model: str
    messages: list[_MockChatMessage]
    response_format: dict[str, Any] | None = None


INTENTS: dict[str, dict[str, Any]] = {
    "surprise me": {"clarifying_question": (
        "Are you in the mood for a mind-bending thriller, something "
        "heartfelt, or light and funny?"
    )},
    "mind-bending": {"clarifying_question": (
        "How much time do you have for this movie?"
    )},
    "think": {"clarifying_question": (
        "How much time do you have for this movie?"
    )},
    "about two hours": {
        "mood": "tense",
        "pace": "moderate",
        "ending_type": "mind-blowing twist",
        "themes": ["mind-bending", "time", "puzzle"],
        "genres_include": ["Science Fiction", "Thriller"],
    },
}
EMPTY_INTENT = {
    "mood": None, "pace": None, "ending_type": None, "themes": [],
    "themes_exclude": [], "genres_include": [], "genres_exclude": [],
    "violence_tolerance": None, "similar_to": [], "time_period": None,
    "runtime_max": None, "clarifying_question": None,
}

# Explanations cite only real shared attributes (Arrival shares Science
# Fiction + time with Interstellar/BR2049; the Wormhole movies share
# Science Fiction + mind-bending/time/puzzle). Passes the Module 5
# grounding check, which runs for real in this backend.
ARRIVAL_EXPLANATION = (
    "{title} is a Science Fiction, Drama film that explores time and "
    "first contact, like Interstellar (10/10), delivering the tense, "
    "mind-blowing tone you asked for."
)
DEFAULT_EXPLANATION = (
    "{title} is a Science Fiction film that explores mind-bending puzzles "
    "and time, delivering the tense, mind-blowing tone you asked for."
)


def intent_reply(message: str) -> dict[str, Any]:
    lowered = message.lower()
    for needle, payload in INTENTS.items():
        if needle in lowered:
            return {**EMPTY_INTENT, **payload}
    return dict(EMPTY_INTENT)


def build_mock_app() -> FastAPI:
    mock = FastAPI()

    @mock.post("/v1/chat/completions")
    async def chat_completions(request: _MockChatRequest) -> dict[str, Any]:
        user_message = next(
            (m.content for m in request.messages if m.role == "user"), ""
        )
        if request.response_format == {"type": "json_object"}:
            new_message = user_message.split("New user message:")[-1].lower()
            content = json.dumps(intent_reply(new_message))
        else:
            title_match = re.search(r"Movie: (.+)", user_message)
            title = title_match.group(1).strip() if title_match else "This movie"
            template = (
                ARRIVAL_EXPLANATION if "Arrival" in title else DEFAULT_EXPLANATION
            )
            content = template.format(title=title)
        return {
            "id": "chatcmpl-demo",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @mock.post("/v1/embeddings")
    async def embeddings(payload: dict[str, Any]) -> dict[str, Any]:
        inputs = payload["input"]
        return {
            "data": [
                {"index": index, "embedding": [0.1] * 1536}
                for index in range(len(inputs))
            ]
        }

    return mock


def start_mock_server() -> tuple[Any, Any]:
    server = uvicorn.Server(
        uvicorn.Config(build_mock_app(), host="127.0.0.1", port=MOCK_PORT,
                       log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    return server, thread


def main() -> None:
    os.environ["OPENAI_API_KEY"] = "demo-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
    os.environ["LLM_MODEL"] = "demo-model"

    from app.core.config import get_settings

    get_settings.cache_clear()
    logging.disable(logging.WARNING)

    server, thread = start_mock_server()
    assert server.started, "mock LLM server failed to start"

    movies = seed_movies()
    arrival = movie_by_title(movies, "Arrival")
    user = User(id=DEMO_USER_ID, email="demo@cinemind.local", hashed_password="x")
    db = DispatchingFakeSession(
        movies, seed_ratings(movies), seed_snapshots(), user
    )

    async def _yield_session() -> AsyncGenerator[DispatchingFakeSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = _yield_session

    @app.get("/api/demo/urls")
    def demo_urls() -> dict[str, str]:
        """Convenience for the E2E demo (demo backend only)."""
        return {
            "user_id": str(DEMO_USER_ID),
            "taste_evolution": f"http://localhost:3000/taste-evolution?user={DEMO_USER_ID}",
            "graph": f"http://localhost:3000/movie/{arrival.id}?user={DEMO_USER_ID}",
            "graph_api": (
                f"http://localhost:{API_PORT}/api/movies/{arrival.id}"
                f"/recommendation-graph?user_id={DEMO_USER_ID}"
            ),
        }

    print("=" * 70)
    print("CineMind demo backend (real pipeline, mock LLM + fake Postgres)")
    print(f"  API      : http://localhost:{API_PORT}   (docs at /docs)")
    print(f"  test user: {DEMO_USER_ID}")
    print(f"  evolution: {demo_urls()['taste_evolution']}")
    print(f"  graph    : {demo_urls()['graph']}")
    print("=" * 70)

    try:
        uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="warning")
    finally:
        app.dependency_overrides.clear()
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
