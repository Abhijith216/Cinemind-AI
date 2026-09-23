"""Live demo for Module 7 — personality backfill over a 20-movie batch.

Runs the REAL backfill pipeline (dossier -> system prompt -> JSON mode ->
MoviePersonalityOut validation -> per-batch commit) against a local
OpenAI-compatible chat server whose "model" scores movies from the dossier
with a fixed genre/keyword heuristic — so results are deterministic without
an API key. No Postgres needed either: the resumable fake session from the
test suite stands in for it.

Then prints three sample personality vectors (comedy / mind-bending sci-fi /
grim thriller) and sanity-checks them the way you'd eyeball real data.

Run from backend/:

    ../.venv/Scripts/python scripts/demo_personality.py
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

MOCK_PORT = 8951

# --- fake DB: 20 movies across 3 archetypes --------------------------------------


class FakeMovie:
    def __init__(self, id: int, title: str, genres: list[str], keywords: list[str]) -> None:
        self.id = id
        self.title = title
        self.overview = f"{title}: a film of its kind."
        self.genres = genres
        self.keywords = keywords
        self.release_year = 2015
        self.personality: dict[str, int] | None = None


def make_movies() -> list[FakeMovie]:
    comedies = [
        FakeMovie(i, f"Wedding Chaos {i}", ["Comedy"],
                  ["wedding", "friendship", "pranks"])
        for i in range(1, 8)
    ]
    scifi = [
        FakeMovie(i, f"Wormhole Protocol {i}", ["Science Fiction", "Drama"],
                  ["time", "space", "father-daughter relationship"])
        for i in range(8, 15)
    ]
    thrillers = [
        FakeMovie(i, f"Midnight Confession {i}", ["Thriller", "Crime"],
                  ["serial killer", "investigation", "obsession"])
        for i in range(15, 21)
    ]
    return comedies + scifi + thrillers  # 20 movies


# --- SQL-aware fake session (mirrors the test suite's) -----------------------------


class FakeResult:
    def __init__(self, items: list[FakeMovie]) -> None:
        self._items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[FakeMovie]:
        return self._items


class FakeSession:
    def __init__(self, movies: list[FakeMovie]) -> None:
        self._movies = movies
        self.committed = 0

    async def scalars(self, statement: object) -> FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
        excluded: set[int] = set()
        if "NOT IN" in compiled:
            inside = compiled.split("NOT IN (")[1].split(")")[0]
            excluded = {int(n) for n in re.findall(r"\d+", inside)}
        limit_match = re.search(r"LIMIT (\d+)", compiled)
        limit = int(limit_match.group(1)) if limit_match else None
        available = [
            m for m in self._movies
            if m.personality is None and m.id not in excluded
        ]
        if limit is not None:
            available = available[:limit]
        return FakeResult(available)

    async def commit(self) -> None:
        self.committed += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSessionmaker:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


# --- mock LLM: deterministic genre/keyword heuristic "model" -----------------------


class _MockChatMessage(BaseModel):
    role: str
    content: str


class _MockChatRequest(BaseModel):
    model: str
    messages: list[_MockChatMessage]
    response_format: dict[str, Any] | None = None


def heuristic_vector(dossier: str) -> dict[str, int]:
    """A tiny deterministic stand-in for the LLM's internal judgment."""
    lowered = dossier.lower()
    is_comedy = "comedy" in lowered or "wedding" in lowered
    is_scifi = "science fiction" in lowered
    is_thriller = "thriller" in lowered or "serial killer" in lowered

    vector = {
        "emotion": 50, "mind_blowing": 30, "darkness": 40, "humor": 35,
        "violence": 30, "romance": 30, "hopefulness": 50,
        "plot_complexity": 40, "rewatchability": 45,
    }
    if is_comedy:
        vector.update(humor=88, darkness=18, violence=12, emotion=45,
                      hopefulness=80, mind_blowing=10, plot_complexity=25)
    if is_scifi:
        vector.update(mind_blowing=85, plot_complexity=78, emotion=75,
                      darkness=45, hopefulness=60, rewatchability=70)
    if is_thriller:
        vector.update(darkness=82, violence=68, humor=8, mind_blowing=55,
                      plot_complexity=70, hopefulness=20, emotion=60)
    if "father-daughter" in lowered:
        vector["emotion"] = 90
    return vector


def build_mock_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: _MockChatRequest) -> dict[str, Any]:
        assert request.response_format == {"type": "json_object"}, "JSON mode required"
        dossier = next(
            (m.content for m in request.messages if m.role == "user"), ""
        )
        content = json.dumps(heuristic_vector(dossier))
        return {
            "id": "chatcmpl-demo",
            "object": "chat.completion",
            "model": request.model,
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


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


# --- the demo ------------------------------------------------------------------------


async def run_backfill(sessionmaker: FakeSessionmaker) -> Any:
    from app.services.personality import backfill_personality

    return await backfill_personality(batch_size=7, limit=20, sessionmaker=sessionmaker)  # type: ignore[arg-type]


def show(title: str, movie: FakeMovie) -> None:
    assert movie.personality is not None
    print(f"\n{title}  ({', '.join(movie.genres)}; keywords: {', '.join(movie.keywords)})")
    for trait, value in movie.personality.items():
        bar = "#" * (value // 5)
        print(f"  {trait:<16} {value:>3}  {bar}")


def sanity_check(label: str, movie: FakeMovie, checks: list[tuple[str, bool]]) -> None:
    passed = all(ok for _label, ok in checks)
    print(f"  {label}: {'PASS' if passed else 'FAIL'}")
    for name, ok in checks:
        print(f"    {'ok' if ok else 'FAILED'}  {name}")


async def main() -> None:
    server, _thread = start_mock_server()
    os.environ["OPENAI_API_KEY"] = "demo-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
    os.environ["LLM_MODEL"] = "demo-model"

    from app.core.config import get_settings

    get_settings.cache_clear()
    logging.disable(logging.INFO)  # keep the demo output readable

    movies = make_movies()
    session = FakeSession(movies)
    stats = await run_backfill(FakeSessionmaker(session))

    print("=" * 72)
    print(f"Backfill of {stats.scored} movies (batch_size=7): scored={stats.scored}, "
          f"failed={stats.failed}, remaining={stats.remaining}")
    print("=" * 72)

    show("Sample 1 - comedy:", movies[0])
    show("Sample 2 - mind-bending sci-fi:", movies[7])
    show("Sample 3 - grim thriller:", movies[14])

    print("\nSanity checks")
    print("-" * 72)
    sanity_check("comedy", movies[0], [
        ("humor high (>=70)", movies[0].personality["humor"] >= 70),
        ("darkness low (<=35)", movies[0].personality["darkness"] <= 35),
        ("violence low (<=35)", movies[0].personality["violence"] <= 35),
    ])
    sanity_check("mind-bending sci-fi", movies[7], [
        ("mind_blowing high (>=70)", movies[7].personality["mind_blowing"] >= 70),
        ("plot_complexity high (>=65)", movies[7].personality["plot_complexity"] >= 65),
        ("emotion boosted by father-daughter theme (>=85)",
         movies[7].personality["emotion"] >= 85),
    ])
    sanity_check("grim thriller", movies[14], [
        ("darkness high (>=70)", movies[14].personality["darkness"] >= 70),
        ("humor low (<=20)", movies[14].personality["humor"] <= 20),
        ("violence elevated (>=55)", movies[14].personality["violence"] >= 55),
    ])

    print("\nAll 20 vectors went through MoviePersonalityOut validation: every")
    print("trait is an int 0-100, exactly the shape stored in movies.personality.")

    server.should_exit = True
    _thread.join(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
