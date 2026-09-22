"""Live demo for Module 4 — parse_query against a local OpenAI-compatible server.

No API key needed: the script starts a small FastAPI app that speaks the
``POST /v1/chat/completions`` protocol (JSON mode, deterministic responses)
on 127.0.0.1:8944, points the app's OPENAI_BASE_URL at it, and runs
``parse_query`` through the REAL pipeline (system prompt -> JSON mode ->
Pydantic validation -> ambiguity handling).

Run from backend/:

    ../.venv/Scripts/python scripts/demo_query_understanding.py

To run against the real OpenAI API instead, set OPENAI_API_KEY +
OPENAI_BASE_URL and delete the mock-server block — the code path below it is
identical.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

MOCK_PORT = 8944


class _MockChatMessage(BaseModel):
    """Module-level so FastAPI can resolve annotations (closure classes break it)."""

    role: str
    content: str


class _MockChatRequest(BaseModel):
    model: str
    messages: list[_MockChatMessage]
    response_format: dict[str, Any] | None = None

# Deterministic replies keyed on a substring of the user message.
MOCK_REPLIES: list[tuple[str, dict[str, Any]]] = [
    (
        "interstellar",
        {
            "mood": "emotional",
            "pace": "moderate",
            "ending_type": "mind-blowing twist",
            "themes": ["father-daughter relationship", "time"],
            "themes_exclude": ["space"],
            "genres_include": ["Science Fiction", "Drama"],
            "genres_exclude": [],
            "violence_tolerance": None,
            "similar_to": ["Interstellar"],
            "time_period": None,
            "runtime_max": None,
            "clarifying_question": None,
        },
    ),
    ("bad day", {
        "mood": "uplifting, comforting", "pace": "moderate", "ending_type": "happy",
        "themes": ["feel-good"], "themes_exclude": [], "genres_include": ["Comedy"],
        "genres_exclude": [], "violence_tolerance": None, "similar_to": [],
        "time_period": None, "runtime_max": None, "clarifying_question": None,
    }),
    ("surprise me", {
        "mood": None, "pace": None, "ending_type": None, "themes": [],
        "themes_exclude": [], "genres_include": [], "genres_exclude": [],
        "violence_tolerance": None, "similar_to": [], "time_period": None,
        "runtime_max": None,
        "clarifying_question": (
            "Are you in the mood for a mind-bending thriller, something "
            "heartfelt, or light and funny?"
        ),
    }),
    ("funnier", {
        "mood": "emotional but humorous", "pace": None, "ending_type": None,
        "themes": [], "themes_exclude": ["space"],
        "genres_include": ["Comedy", "Drama"], "genres_exclude": [],
        "violence_tolerance": None, "similar_to": ["Interstellar"],
        "time_period": None, "runtime_max": None, "clarifying_question": None,
    }),
]


def build_mock_app() -> FastAPI:
    """Minimal OpenAI-compatible chat.completions endpoint (JSON mode)."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: _MockChatRequest) -> dict[str, Any]:
        assert request.response_format == {"type": "json_object"}, (
            "demo requires JSON mode"
        )
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"),
            "",
        )
        # Match the NEW message only ("New user message: ..."), never the
        # embedded history JSON, or multi-turn demos would re-match old turns.
        new_message = last_user.split("New user message:")[-1].lower()
        for needle, payload in MOCK_REPLIES:
            if needle in new_message:
                content = json.dumps(payload)
                break
        else:
            content = json.dumps(
                {**{k: ([] if isinstance(MOCK_REPLIES[0][1][k], list) else None)
                    for k in MOCK_REPLIES[0][1]}, "clarifying_question": None}
            )
        return {
            "id": "chatcmpl-demo",
            "object": "chat.completion",
            "model": request.model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content},
                 "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


def start_mock_server() -> tuple[Any, Any]:
    """Run the mock server in a background thread; return (server, thread)."""
    server = uvicorn.Server(
        uvicorn.Config(
            build_mock_app(),
            host="127.0.0.1",
            port=MOCK_PORT,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    return server, thread


async def main() -> None:
    server, _thread = start_mock_server()
    os.environ["OPENAI_API_KEY"] = "demo-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
    os.environ["LLM_MODEL"] = "demo-model"
    os.environ.pop("OPENAI_API_BASE", None)

    # Imported AFTER env vars are set so settings pick up the mock URL.
    from app.core.config import get_settings
    get_settings.cache_clear()

    from app.services.query_understanding import AmbiguousQueryError, parse_query

    history = [
        {"role": "user", "content": "something like Interstellar but not about space"},
        {"role": "assistant", "content": json.dumps(MOCK_REPLIES[0][1])},
    ]

    print("=" * 72)
    print("parse_query('something like Interstellar but not about space, "
          "emotional,\\n            mind-blowing ending')")
    print("=" * 72)
    intent = await parse_query(
        "something like Interstellar but not about space, emotional, "
        "mind-blowing ending"
    )
    print(json.dumps(intent.model_dump(mode="json"), indent=2))

    print()
    print("=" * 72)
    print("parse_query('surprise me')  ->  ambiguous by design")
    print("=" * 72)
    try:
        await parse_query("surprise me")
    except AmbiguousQueryError as exc:
        print("clarifying_question:", exc.question)

    print()
    print("=" * 72)
    print("parse_query('actually make it funnier', history=[...])  ->  multi-turn")
    print("=" * 72)
    refined = await parse_query("actually make it funnier", history)
    print(json.dumps(refined.model_dump(mode="json"), indent=2))

    server.should_exit = True
    _thread.join(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
