"""Tests for Module 4 query understanding (offline: fake LLM client).

Covers the five required scenarios:
1. specific request ("like Interstellar but not space")
2. mood-only request ("I'm having a bad day")
3. ambiguous request ("surprise me") → clarifying question
4. explicit exclusions ("horror, no gore")
5. multi-turn follow-up refining a previous query
Plus client-level behavior (JSON mode, self-repair).
"""

import asyncio
from typing import Any

import httpx
import pytest

from app.schemas.intent import QueryIntent
from app.services.llm_client import ChatLLMClient, LLMError
from app.services.query_understanding import (
    AmbiguousQueryError,
    _history_to_messages,
    parse_query,
)


class FakeChatClient:
    """Programmable stand-in for ChatLLMClient."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[QueryIntent],
        history: Any = (),
    ) -> QueryIntent:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "history": history}
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema_model.model_validate(response)

    async def aclose(self) -> None:
        return None


def interstellar_intent() -> dict[str, Any]:
    return {
        "mood": "emotional",
        "pace": "moderate",
        "ending_type": "mind-blowing twist",
        "themes": ["space exploration", "father-daughter relationship"],
        "themes_exclude": ["space"],
        "genres_include": ["Science Fiction", "Drama"],
        "genres_exclude": [],
        "violence_tolerance": None,
        "similar_to": ["Interstellar"],
        "time_period": None,
        "runtime_max": None,
        "clarifying_question": None,
    }


# --- 1. specific request ------------------------------------------------------


@pytest.mark.asyncio
async def test_specific_request_like_interstellar_but_not_space() -> None:
    client = FakeChatClient([interstellar_intent()])

    intent = await parse_query(
        "something like Interstellar but not about space, emotional, "
        "mind-blowing ending",
        client=client,  # type: ignore[arg-type]
    )

    assert intent.similar_to == ["Interstellar"]
    assert intent.themes_exclude == ["space"]  # theme, not genre
    assert intent.genres_include == ["Science Fiction", "Drama"]
    assert "Science Fiction" in (intent.genres_include or [])
    assert intent.ending_type == "mind-blowing twist"
    assert intent.clarifying_question is None


# --- 2. mood-only request ------------------------------------------------------


@pytest.mark.asyncio
async def test_mood_only_request_bad_day() -> None:
    client = FakeChatClient(
        [
            {
                "mood": "uplifting, comforting",
                "pace": "moderate",
                "ending_type": "happy",
                "themes": ["feel-good"],
                "themes_exclude": [],
                "genres_include": ["Comedy"],
                "genres_exclude": [],
                "violence_tolerance": None,
                "similar_to": [],
                "time_period": None,
                "runtime_max": None,
                "clarifying_question": None,
            }
        ]
    )

    intent = await parse_query(
        "I'm having a bad day and want something warm",
        client=client,  # type: ignore[arg-type]
    )

    assert intent.mood is not None and "uplifting" in intent.mood
    assert intent.ending_type == "happy"
    # No structural constraints beyond mood/genre vibes:
    assert intent.similar_to == []
    assert intent.themes_exclude == []


# --- 3. ambiguous request ------------------------------------------------------


@pytest.mark.asyncio
async def test_ambiguous_request_returns_clarifying_question() -> None:
    client = FakeChatClient(
        [
            {
                "mood": None,
                "pace": None,
                "ending_type": None,
                "themes": [],
                "themes_exclude": [],
                "genres_include": [],
                "genres_exclude": [],
                "violence_tolerance": None,
                "similar_to": [],
                "time_period": None,
                "runtime_max": None,
                "clarifying_question": (
                    "When you say surprise me — want an emotional rollercoaster, "
                    "a mind-bending thriller, or something light and funny?"
                ),
            }
        ]
    )

    with pytest.raises(AmbiguousQueryError) as excinfo:
        await parse_query("surprise me", client=client)  # type: ignore[arg-type]

    question = excinfo.value.question
    assert question and "surprise" in client.calls[0]["user"]
    assert excinfo.value.intent is not None
    assert excinfo.value.intent.mood is None  # no forced guess


# --- 4. explicit exclusions -----------------------------------------------------


@pytest.mark.asyncio
async def test_request_with_explicit_exclusions() -> None:
    client = FakeChatClient(
        [
            {
                "mood": "tense",
                "pace": None,
                "ending_type": None,
                "themes": ["revenge"],
                "themes_exclude": ["gore"],
                "genres_include": ["Thriller"],
                "genres_exclude": ["Horror"],
                "violence_tolerance": "medium",
                "similar_to": [],
                "time_period": None,
                "runtime_max": None,
                "clarifying_question": None,
            }
        ]
    )

    intent = await parse_query(
        "a tense thriller about revenge, but no horror movies and nothing gory",
        client=client,  # type: ignore[arg-type]
    )

    assert intent.genres_exclude == ["Horror"]
    assert "gore" in intent.themes_exclude
    assert intent.violence_tolerance == "medium"


# --- 5. multi-turn refinement ----------------------------------------------------


@pytest.mark.asyncio
async def test_multi_turn_followup_refines_previous_query() -> None:
    history = [
        {
            "role": "user",
            "content": "something like Interstellar but not about space",
        },
        {
            "role": "assistant",
            "content": '{"similar_to": ["Interstellar"], '
            '"themes_exclude": ["space"], "mood": "emotional"}',
        },
        {"role": "user", "content": "actually make it funnier"},
    ]
    client = FakeChatClient(
        [
            {
                "mood": "emotional but humorous",
                "pace": None,
                "ending_type": None,
                "themes": [],
                "themes_exclude": ["space"],
                "genres_include": ["Comedy", "Drama"],
                "genres_exclude": [],
                "violence_tolerance": None,
                "similar_to": ["Interstellar"],
                "time_period": None,
                "runtime_max": None,
                "clarifying_question": None,
            }
        ]
    )

    intent = await parse_query("actually make it funnier", history, client=client)  # type: ignore[arg-type]

    # The refined intent keeps the prior constraints (space exclusion) while
    # shifting tone — that's what "refine" means here.
    assert intent.themes_exclude == ["space"]
    assert intent.similar_to == ["Interstellar"]
    assert intent.mood is not None and "humor" in intent.mood.lower()
    # History actually reached the prompt:
    assert "make it funnier" in client.calls[0]["user"]
    assert "actually make it funnier" in client.calls[0]["user"]


# --- helpers / client plumbing ----------------------------------------------------


def test_history_mapper_ignores_invalid_roles_and_empty_content() -> None:
    mapped = _history_to_messages(
        [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "nope"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "hi there"},
        ]
    )
    assert mapped == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_history_mapper_handles_none() -> None:
    assert _history_to_messages(None) == []


def test_intent_schema_coerces_runtime_string() -> None:
    intent = QueryIntent.model_validate({"runtime_max": "150 minutes"})
    assert intent.runtime_max == 150


def test_intent_schema_normalizes_violence_tolerance() -> None:
    intent = QueryIntent.model_validate({"violence_tolerance": " HIGH "})
    assert intent.violence_tolerance == "high"
    with pytest.raises(ValueError):
        QueryIntent.model_validate({"violence_tolerance": "extreme"})


def test_intent_schema_strips_blank_strings_to_none() -> None:
    intent = QueryIntent.model_validate({"mood": "   "})
    assert intent.mood is None


# --- ChatLLMClient JSON-mode + self-repair ----------------------------------------


def _chat_client_with_responses(responses: list[httpx.Response]) -> ChatLLMClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    return ChatLLMClient(
        api_key="test-key",
        model="test-model",
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(handler),
    )


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


@pytest.mark.asyncio
async def test_client_sends_json_mode_and_repairs_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            # First attempt: broken JSON (trailing comma).
            return _chat_response('{"mood": "tense",}')
        return _chat_response('{"mood": "tense"}')

    sleeps: list[float] = []
    monkeypatch.setattr(
        "app.services.llm_client.asyncio.sleep", lambda d: sleeps.append(d) or _noop()
    )

    client = _chat_client_with_responses([])
    # Inject our handler-based transport responses manually:
    client._client = httpx.AsyncClient(  # noqa: SLF001 - test-only rewire
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(handler),
    )

    intent = await client.complete_json(
        system_prompt="sys",
        user_prompt="user",
        schema_model=QueryIntent,
    )
    await client.aclose()

    assert intent.mood == "tense"
    assert len(requests) == 2  # original + repair round-trip
    first_body = requests[0].read().decode()
    assert '"response_format":{"type":"json_object"}' in first_body
    repair_body = requests[1].read().decode()
    assert "did not match the required schema" in repair_body


async def _noop() -> None:
    return None


def test_client_raises_on_permanent_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = ChatLLMClient(
        api_key="k",
        model="m",
        base_url="https://llm.test/v1",
        transport=httpx.MockTransport(handler),
    )

    async def run() -> None:
        await client.complete_json(
            system_prompt="s", user_prompt="u", schema_model=QueryIntent
        )

    with pytest.raises(LLMError):
        asyncio.run(run())


def test_client_rejects_empty_api_key() -> None:
    with pytest.raises(LLMError):
        ChatLLMClient(api_key="", model="m", base_url="https://llm.test/v1")
