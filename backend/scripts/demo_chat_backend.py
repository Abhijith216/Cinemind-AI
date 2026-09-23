"""Long-running local CineMind backend for frontend E2E work.

Runs the REAL FastAPI app (real orchestrator, parse_query, hybrid retrieval,
grounded explanations) with two offline seams — the same ones as
``demo_chat.py``:

- a local OpenAI-compatible server plays the chat model AND embeddings;
- a SQL-dispatching fake session stands in for Postgres.

Run from backend/:

    ../.venv/Scripts/python scripts/demo_chat_backend.py

Then `cd frontend && npm run dev` and open http://localhost:3000/chat
(the backend CORS default is exactly that origin).

Scripted conversation (drives the quick-reply chips in the UI):

    "surprise me"          -> clarifying: mood?
    "mind-bending thriller"-> clarifying: how much time?
    "about two hours"      -> final ranked + explained results
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.db import get_db_session
from app.main import app
from app.models import ChatMessage, ChatSession, Movie

MOCK_PORT = 8953
API_PORT = 8000


def seed_movies() -> list[Movie]:
    return [
        Movie(
            id=uuid.uuid4(),
            tmdb_id=600000 + index,
            title=f"Wormhole Protocol {index}",
            overview="A tense, mind-bending science fiction puzzle.",
            release_year=2014 + index,
            runtime=118,
            genres=["Science Fiction", "Drama"],
            keywords=["time", "mind-bending", "puzzle"],
            language="en",
            vote_average=8.0,
            vote_count=3000,
            popularity=90.0 + index,
            personality={
                "emotion": 80, "mind_blowing": 90, "darkness": 40, "humor": 20,
                "violence": 25, "romance": 25, "hopefulness": 55,
                "plot_complexity": 85, "rewatchability": 75,
            },
        )
        for index in range(1, 5)
    ]


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class DispatchingFakeSession:
    """Postgres stand-in that sniffs each statement's tables."""

    def __init__(self, movies: list[Movie]) -> None:
        self.movies = movies
        self.added: list[Any] = []

    async def get(self, model: Any, key: Any) -> Any:
        for obj in self.added:
            if isinstance(obj, model) and getattr(obj, "id", None) == key:
                return obj
        return None

    async def execute(self, statement: Any) -> FakeResult:
        sql = str(statement)
        if "chat_messages" in sql:
            messages = [obj for obj in self.added if isinstance(obj, ChatMessage)]
            messages.sort(key=lambda message: message.created_at)
            return FakeResult(messages)
        if "<=>" in sql:
            return FakeResult(
                [(movie, 0.92 - index * 0.07) for index, movie in enumerate(self.movies)]
            )
        if "ratings" in sql:
            return FakeResult([])
        raise AssertionError(f"unexpected statement: {sql[:120]}")

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

# Every token is real data or generic discourse -> passes the Module 5
# grounding check, which runs for real in this backend.
EXPLANATION_TEMPLATE = (
    "{title} is a Science Fiction, Drama film that explores time and "
    "mind-bending puzzles, delivering the tense, mind-blowing tone you asked for."
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
            content = EXPLANATION_TEMPLATE.format(title=title)
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

    db = DispatchingFakeSession(seed_movies())

    async def _yield_session() -> AsyncGenerator[DispatchingFakeSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = _yield_session

    print("=" * 70)
    print("CineMind demo backend (real pipeline, mock LLM + fake Postgres)")
    print(f"  API      : http://localhost:{API_PORT}   (docs at /docs)")
    print("  Frontend : cd frontend && npm run dev -> http://localhost:3000/chat")
    print("  Script   : surprise me -> mind-bending thriller -> about two hours")
    print("=" * 70)

    try:
        uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="warning")
    finally:
        app.dependency_overrides.clear()
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
