"""Live demo for Module 8 — the product-spec conversation, end to end.

Reproduces the required flow across 4 turns against the REAL
``POST /api/chat/message`` (real orchestrator, real parse_query, real
hybrid retrieval pipeline shape, real grounded explanations):

    1. "surprise me"      -> clarifying question (no search)
    2. "think"            -> second clarifying question (no search)
    3. "about two hours"  -> final ranked + explained results

Infrastructure: a local OpenAI-compatible server plays the chat model AND
the embedding endpoint; a SQL-dispatching fake session stands in for
Postgres (chat_messages selects return the persisted turns, cosine
candidate selects return the seeded movies, rating joins return nothing).
Every layer above the database is the production code path.

Run from backend/:

    ../.venv/Scripts/python scripts/demo_chat.py
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
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.db import get_db_session
from app.main import app
from app.models import ChatMessage, ChatSession, Movie

MOCK_PORT = 8953

# --- seeded catalog (the fake Postgres) ---------------------------------------------


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
    """Stands in for Postgres by sniffing each statement's tables.

    - chat_messages select  -> persisted turns (history)
    - cosine candidate select (``<=>``) -> seeded movies + similarity
    - ratings joins -> no rating history (anonymous user)
    """

    def __init__(self, movies: list[Movie]) -> None:
        self.movies = movies
        self.added: list[Any] = []
        self.commits = 0

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
            return FakeResult([])  # anonymous: no rating history / taste
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


# --- mock OpenAI-compatible server (chat JSON mode + plain text + embeddings) --------


class _MockChatMessage(BaseModel):
    role: str
    content: str


class _MockChatRequest(BaseModel):
    model: str
    messages: list[_MockChatMessage]
    response_format: dict[str, Any] | None = None


# Intent replies keyed on the NEW user message only (never the history JSON).
INTENTS: dict[str, dict[str, Any]] = {
    "surprise me": {"clarifying_question": (
        "Are you in the mood for a mind-bending thriller, something "
        "heartfelt, or light and funny?"
    )},
    "think": {"clarifying_question": "How much time do you have for this movie?"},
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

# Explanation wording — every token is real data or generic discourse, so it
# passes the Module 5 grounding check (which runs for real in this demo).
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
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: _MockChatRequest) -> dict[str, Any]:
        user_message = next(
            (m.content for m in request.messages if m.role == "user"), ""
        )
        if request.response_format == {"type": "json_object"}:
            # parse_query embeds history JSON — match the NEW message only.
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

    @app.post("/v1/embeddings")
    async def embeddings(payload: dict[str, Any]) -> dict[str, Any]:
        inputs = payload["input"]
        return {
            "data": [
                {"index": index, "embedding": [0.1] * 1536}
                for index in range(len(inputs))
            ]
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


# --- the scripted 4-turn conversation -------------------------------------------------


def main() -> None:
    server, _thread = start_mock_server()
    os.environ["OPENAI_API_KEY"] = "demo-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
    os.environ["LLM_MODEL"] = "demo-model"

    from app.core.config import get_settings

    get_settings.cache_clear()
    logging.disable(logging.WARNING)

    db = DispatchingFakeSession(seed_movies())

    async def _yield_session() -> AsyncGenerator[DispatchingFakeSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = _yield_session
    client = TestClient(app)

    conversation: list[tuple[str, str, str | None]] = []  # (turn label, json, note)
    session_id: str | None = None
    script = [
        ("Turn 1", "surprise me", None),
        ("Turn 2", "think", None),
        ("Turn 3", "about two hours", None),
        ("Turn 4", "something shorter", None),
    ]

    for label, message, _note in script:
        payload: dict[str, Any] = {"message": message}
        if session_id is not None:
            payload["session_id"] = session_id
        response = client.post("/api/chat/message", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        session_id = body["session_id"]
        conversation.append((label, message, body))

    print("=" * 74)
    print("CineMind chat - the product-spec flow, 4 turns via POST /chat/message")
    print("=" * 74)
    for label, message, body in conversation:
        assert body is not None
        print(f"\n{label}")
        print(f"  user      : {message}")
        print(f"  assistant : {body['reply']}")
        if body["asked_clarifying_question"]:
            print("  (clarifying question - no search this turn)")
        else:
            intent = body.get("intent") or {}
            print(
                f"  intent    : mood={intent.get('mood')!r}, "
                f"ending={intent.get('ending_type')!r}, "
                f"themes={intent.get('themes')}, "
                f"genres={intent.get('genres_include')}, "
                f"runtime_max={intent.get('runtime_max')}"
            )
            for index, result in enumerate(body["results"], start=1):
                attrs = result["matched_attributes"]
                print(
                    f"    {index}. {result['movie']['title']} "
                    f"(score {result['final_score']:.3f})"
                )
                print(f"       why: {result['explanation']}")
                print(
                    f"       matched: genres={attrs['genres']} "
                    f"themes={attrs['themes']}"
                )

    persisted = [obj for obj in db.added if isinstance(obj, ChatMessage)]
    print("\n" + "=" * 74)
    print(
        f"Persisted: {len([o for o in db.added if isinstance(o, ChatSession)])} "
        f"chat_session, {len(persisted)} chat_messages "
        f"({len([m for m in persisted if m.role == 'user'])} user / "
        f"{len([m for m in persisted if m.role == 'assistant'])} assistant); "
        "assistant turns carry intent + result_movie_ids."
    )

    app.dependency_overrides.clear()
    server.should_exit = True
    _thread.join(timeout=5)


if __name__ == "__main__":
    main()
