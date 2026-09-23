"""Live demo for Module 5 — grounded explanations.

Runs the REAL default pipeline for the deliverable case:

    user rated Interstellar 10/10 and Blade Runner 2049 9/10,
    is now being shown Arrival.

No API key needed: a local OpenAI-compatible chat server provides the
wording (the LLM's only job); attribute extraction and the grounding check
run exactly as in production. Then a "lying LLM" round proves the grounding
check rejects invented attributes. Finally a spot-check diffs every noun in
the accepted explanation against Arrival's REAL genres/keywords.

Run from backend/:

    ../.venv/Scripts/python scripts/demo_explain.py
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

MOCK_PORT = 8947

# ---------------------------------------------------------------------------
# Real TMDb attributes (spot-check source — keep in sync with themoviedb.org).
# ---------------------------------------------------------------------------
MOVIES: dict[str, dict[str, Any]] = {
    "Arrival": {
        "genres": ["Science Fiction", "Drama", "Mystery"],
        "keywords": [
            "first contact",
            "time",
            "language",
            "alien communication",
            "based on short story",
        ],
        "personality": {
            "emotion": 85,
            "mind_blowing": 90,
            "darkness": 35,
            "humor": 15,
            "violence": 10,
            "romance": 20,
            "hopefulness": 55,
            "plot_complexity": 85,
            "rewatchability": 65,
        },
    },
    "Interstellar": {
        "genres": ["Science Fiction", "Drama", "Adventure"],
        "keywords": ["time", "father-daughter relationship", "space"],
        "personality": {
            "emotion": 88,
            "mind_blowing": 95,
            "darkness": 45,
            "humor": 20,
            "violence": 25,
            "romance": 25,
            "hopefulness": 60,
            "plot_complexity": 85,
            "rewatchability": 80,
        },
    },
    "Blade Runner 2049": {
        "genres": ["Science Fiction", "Drama", "Mystery"],
        "keywords": ["artificial intelligence", "future", "identity"],
        "personality": {
            "emotion": 80,
            "mind_blowing": 80,
            "darkness": 65,
            "humor": 10,
            "violence": 45,
            "romance": 20,
            "hopefulness": 35,
            "plot_complexity": 90,
            "rewatchability": 70,
        },
    },
}

LOVED_RATINGS = [("Interstellar", 10), ("Blade Runner 2049", 9)]

# Verified-overlap wording only — every noun below is checked against the
# vocabulary the service actually passes to the model.
GOOD_SENTENCE = (
    "Arrival is a Science Fiction, Drama film that explores time, "
    "sharing real ground with Interstellar (10/10) and Blade Runner 2049 (9/10). "
    "It delivers the emotional, mind blowing tone you asked for."
)

# Deliberately invents attributes that exist nowhere in the data.
LYING_SENTENCE = (
    "Arrival is a hilarious action comedy full of explosive car chases "
    "and robot sidekicks."
)


class _MockChatMessage(BaseModel):
    role: str
    content: str


class _MockChatRequest(BaseModel):
    model: str
    messages: list[_MockChatMessage]
    response_format: dict[str, Any] | None = None


def build_mock_app() -> FastAPI:
    """OpenAI-compatible chat.completions returning a canned explanation."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat_completions(request: _MockChatRequest) -> dict[str, Any]:
        assert not request.response_format, "explanations use plain-text mode"
        user_message = next(
            (m.content for m in request.messages if m.role == "user"), ""
        ).lower()
        reply = GOOD_SENTENCE if "only things you may reference" in user_message else "ok"
        return {
            "id": "chatcmpl-demo",
            "object": "chat.completion",
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return app


def start_mock_server() -> tuple[Any, Any]:
    server = uvicorn.Server(
        uvicorn.Config(
            build_mock_app(), host="127.0.0.1", port=MOCK_PORT, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    return server, thread


async def main() -> None:
    # The expected "failed grounding check" warnings are demo noise.
    logging.disable(logging.WARNING)
    server, _thread = start_mock_server()
    os.environ["OPENAI_API_KEY"] = "demo-key"
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{MOCK_PORT}/v1"
    os.environ["LLM_MODEL"] = "demo-model"

    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.schemas.explanation import LovedMovie, UserTasteContext
    from app.schemas.intent import QueryIntent
    from app.services.explain import explain_recommendation

    taste = UserTasteContext(
        loved_movies=[
            LovedMovie(
                title=title,
                score=float(score),
                genres=MOVIES[title]["genres"],
                keywords=MOVIES[title]["keywords"],
                personality=MOVIES[title]["personality"],
            )
            for title, score in LOVED_RATINGS
        ]
    )
    intent = QueryIntent.model_validate(
        {
            "mood": "emotional",
            "pace": "moderate",
            "ending_type": "mind-blowing twist",
            "themes": ["father-daughter relationship", "time"],
            "themes_exclude": ["space"],
            "genres_include": ["Science Fiction", "Drama"],
            "similar_to": ["Interstellar"],
        }
    )
    arrival = MOVIES["Arrival"]

    class DemoMovie:
        id = "tmdb-329865"
        title = "Arrival"
        genres = arrival["genres"]
        keywords = arrival["keywords"]
        personality = arrival["personality"]

    print("=" * 72)
    print("Case: user rated Interstellar 10/10 + Blade Runner 2049 9/10;")
    print("      now being shown Arrival.")
    print("=" * 72)

    explanation = await explain_recommendation(DemoMovie(), intent, taste)
    print(f"sentence (source={explanation.source}):")
    print(f"  {explanation.text}")
    print("structured matched attributes (graph view):")
    print(json.dumps(explanation.matched_attributes.model_dump(), indent=2))

    print()
    print("=" * 72)
    print("Lying-LLM round: model invents attributes absent from the data")
    print("=" * 72)

    async def lying_llm(prompt: str, *, system_prompt: str) -> str:
        return LYING_SENTENCE

    refused = await explain_recommendation(
        DemoMovie(), intent, taste, llm_caller=lying_llm
    )
    print(f"sentence (source={refused.source}):")
    print(f"  {refused.text}")

    print()
    print("=" * 72)
    print("Spot-check: every content noun vs Arrival's REAL TMDb attributes")
    print("=" * 72)
    real_phrases = {
        *{g.lower() for g in arrival["genres"]},
        *{k.lower() for k in arrival["keywords"]},
        "arrival",
        "interstellar",
        "blade runner 2049",
        "father-daughter relationship",
        "space",
        "artificial intelligence",
        "future",
        "identity",
        *{t.replace("_", " ") for t in arrival["personality"]},
        # Display forms of the movie's real trait scores (emotion 85 ->
        # "emotional"), same mapping the service uses in its labels.
        "emotional",
        "mind blowing",
        "dark",
        "funny",
        "hopeful",
        "romantic",
        "twisty",
        "gripping",
        "violent",
    }
    # Multi-word real attributes legitimize their component words too
    # ("science" comes from "Science Fiction" — real by construction).
    real_vocab = {
        *real_phrases,
        *{word for phrase in real_phrases for word in re.findall(r"[a-z0-9\-]+", phrase)},
    }
    generic_ok = {
        "a", "an", "the", "and", "or", "is", "that", "explores", "sharing",
        "real", "ground", "with", "it", "delivers", "tone", "you", "asked",
        "for", "film", "movie",
    }
    unknown = []
    for token in re.findall(r"[a-z0-9\-]+", explanation.text.lower()):
        if token not in real_vocab and token not in generic_ok and not token.isdigit():
            unknown.append(token)
    if unknown:
        print(f"UNGROUNDABLE tokens found: {sorted(set(unknown))}  <-- fix needed!")
    else:
        print("OK: no token in the explanation falls outside Arrival's real")
        print("    genres/keywords, the loved movies' attributes, or the")
        print("    verified trait scores. Zero invented attributes.")

    server.should_exit = True
    _thread.join(timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
