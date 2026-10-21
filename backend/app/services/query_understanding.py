"""Module 4 — LLM query understanding: free text → structured QueryIntent.

``parse_query`` sends the user's request (plus optional conversation
history) to the configured chat model in JSON mode and validates the reply
against ``QueryIntent``. Ambiguous requests ("surprise me") come back with a
``clarifying_question`` instead of a forced guess, so the chat layer can ask
a follow-up.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas.intent import QueryIntent
from app.services.llm_client import ChatLLMClient, LLMError, create_chat_client

logger = logging.getLogger("app.query_understanding")

_GREETING = re.compile(
    r"\s*(?:(?:hey|hi|hello|howdy|hiya|yo)(?:\s+(?:there|cinemind))?"
    r"|good\s+(?:morning|afternoon|evening))[\s!.,?]*",
    re.IGNORECASE,
)
GREETING_QUESTION = (
    "Hey! What kind of movie are you in the mood for — a comedy, a thriller, or something else?"
)

SYSTEM_PROMPT = """You convert a user's free-text movie request into JSON.

Return ONLY a JSON object with exactly these keys:
{
  "mood": string | null,
  "pace": string | null,
  "ending_type": string | null,
  "themes": string[],
  "themes_exclude": string[],
  "genres_include": string[],
  "genres_exclude": string[],
  "violence_tolerance": "none" | "low" | "medium" | "high" | null,
  "similar_to": string[],
  "time_period": string | null,
  "runtime_max": integer | null,
  "clarifying_question": string | null
}

Field rules:
- themes: topics/subjects the user WANTS (e.g. "space exploration", "heist",
  "artificial intelligence", "father-daughter relationship").
- themes_exclude: topics/subjects the user does NOT want. A phrase like
  "not about space" or "no aliens" belongs here, NOT in genres_exclude
  (genres are broad categories like Science Fiction, Horror, Romance).
- genres_include / genres_exclude: use official-sounding genre names
  (Science Fiction, Drama, Thriller, Comedy, ...). "not about space" is a
  theme exclusion, not a genre exclusion.
- similar_to: movie titles the user references ("like Interstellar").
- violence_tolerance: infer comfort with violent content; null if unstated.
- mood: emotional register ("uplifting", "tense", "melancholic", ...).
- pace: "slow-burn" | "moderate" | "fast-paced" | null.
- ending_type: e.g. "mind-blowing twist", "bittersweet", "happy", "open".
- time_period: release year ("2025"), decade ("1990s"), range ("2020-2026"),
  or "recent" — null if unstated. This is the release period, not the story's setting.
  Represent historical story settings as themes instead.
- runtime_max: minutes, only when the user states a limit.

Ambiguity rule:
If the request is too vague to interpret meaningfully (e.g. "surprise me",
"anything", "I don't know"), leave all fields null/empty and set
clarifying_question to ONE short question that would best narrow it down.
Do not guess fields the user did not state or strongly imply.

Conversation history may be provided: use it to resolve references like
"something happier than that" or "the same but funnier", refining the
PREVIOUS intent rather than starting from scratch.
Preserve the previous resolved request's runtime, exclusions, reference movies,
genres and themes unless the user explicitly changes or removes them.
For "under N minutes", set runtime_max to N-1; "at most N" permits N.
Return at most three reference titles, without appending release years.
Do not infer that an excluded genre is wanted. Use canonical genre names:
Action, Adventure, Animation, Comedy, Crime, Documentary, Drama, Family,
Fantasy, History, Horror, Music, Mystery, Romance, Science Fiction, Thriller,
War, Western.
"""


class AmbiguousQueryError(LLMError):
    """Not a failure: the model asked for clarification instead of guessing.

    Carries the question (for the chat layer to show) and the (mostly empty)
    intent so any partial fields are still available.
    """

    def __init__(self, question: str, intent: QueryIntent | None = None) -> None:
        super().__init__(question)
        self.question = question
        self.intent = intent


def _history_to_messages(
    conversation_history: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Map stored conversation turns to chat messages (role/content only)."""
    messages: list[dict[str, str]] = []
    for turn in conversation_history or []:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    return messages


async def parse_query(
    user_text: str,
    conversation_history: list[dict[str, str]] | None = None,
    *,
    client: ChatLLMClient | None = None,
) -> QueryIntent:
    """Interpret free text (with optional history) into a QueryIntent.

    Raises :class:`AmbiguousQueryError` when the model responds with a
    clarifying question instead of an interpretation.
    """
    # A greeting contains no movie preferences to interpret. Keep this normal
    # conversational turn independent of provider availability and credits.
    if _GREETING.fullmatch(user_text):
        raise AmbiguousQueryError(GREETING_QUESTION)

    owns_client = client is None
    if client is None:
        client = create_chat_client()

    history = _history_to_messages(conversation_history)
    user_prompt = (
        f"Conversation history so far (may be empty): "
        f"{json.dumps(history, ensure_ascii=False)}\n\n"
        f"New user message: {user_text!r}\n\n"
        "Return the JSON object for this request now."
    )

    try:
        intent = await client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema_model=QueryIntent,
            history=(),
        )
    finally:
        if owns_client:
            await client.aclose()

    if intent.clarifying_question:
        logger.info("Movie request needs clarification")
        raise AmbiguousQueryError(intent.clarifying_question, intent)
    # Reference films must originate in the user's conversation, never be
    # invented recommendations used to steer or exclude catalog results.
    user_context = " ".join(
        [user_text, *(turn["content"] for turn in history if turn["role"] == "user")]
    )

    def normalize(value: str) -> str:
        return " ".join(re.findall(r"\w+", value.casefold()))

    context = f" {normalize(user_context)} "
    intent.similar_to = [title for title in intent.similar_to if f" {normalize(title)} " in context]
    return intent


def intent_to_payload(intent: QueryIntent) -> dict[str, Any]:
    """Serialize an intent for logging/debugging (JSON-safe)."""
    return intent.model_dump(mode="json")
