"""Module 8 — Conversational orchestration.

Ties the pipeline together for multi-turn chat:

1. Load the session's conversation history (``chat_messages``).
2. ``parse_query`` with that history so follow-ups ("the same but funnier")
   refine the previous intent (Module 4).
3. If the model answers with a ``clarifying_question``, that question IS the
   turn's reply — no search yet.
4. Otherwise: render the resolved intent, embed it (Module 2), run
   ``hybrid_search`` (Module 3), and ground explanations for every result
   (Module 5 — taste context from Module 6, personality from Module 7).
5. Persist both messages (the assistant turn carries the resolved intent and
   the ordered result movie ids) and commit.

All pipeline steps are injectable callables, so tests and demos drive the
full orchestration offline; production wires the real modules by default.
"""

from __future__ import annotations

import datetime
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, ChatSession
from app.schemas.chat import ChatMovieOut, ChatTurnResponse
from app.schemas.common import MovieOut
from app.schemas.intent import QueryIntent
from app.schemas.retrieval import SearchFilters
from app.services.explain import build_user_taste_context
from app.services.query_understanding import AmbiguousQueryError
from app.services.retrieval import RankedMovie

logger = logging.getLogger("app.chat_orchestrator")

IntentFn = Callable[[str, list[dict[str, str]]], Awaitable[QueryIntent]]
EmbedFn = Callable[[str], Awaitable[list[float]]]
SearchFn = Callable[
    [AsyncSession, list[float], SearchFilters, uuid.UUID | None, int],
    Awaitable[list[RankedMovie]],
]
ExplainFn = Callable[[Any, QueryIntent | None, Any], Awaitable[Any]]


def _filters_from_intent(intent: QueryIntent) -> SearchFilters:
    """Map intent fields onto the hard SQL filters retrieval supports.

    ``genres_include`` become genre filters; ``time_period`` like "1990s"
    (or "recent") becomes a release-year window. ``runtime_max`` has no SQL
    filter yet — it stays in the intent for the LLM/explanation stages.
    """
    year_min: int | None = None
    year_max: int | None = None
    if intent.time_period:
        decade_match = re.search(r"(\d{4})s", intent.time_period.lower())
        if decade_match:
            decade = int(decade_match.group(1))
            if 1900 <= decade <= 2090:
                year_min, year_max = decade, decade + 9
        elif "recent" in intent.time_period.lower():
            year_min = 2020
    return SearchFilters(
        genres=list(intent.genres_include),
        min_release_year=year_min,
        max_release_year=year_max,
    )


def render_intent_text(intent: QueryIntent) -> str:
    """Render the resolved intent as the semantic query text to embed.

    Embedding the intent (not the raw message) is what makes clarification
    turns re-shape the vector: "think" after "surprise me" produces a
    mind-bending query embedding even though the word never appeared before.
    """
    parts: list[str] = []
    if intent.mood:
        parts.append(intent.mood)
    if intent.ending_type:
        parts.append(intent.ending_type)
    parts.extend(intent.themes)
    parts.extend(intent.genres_include)
    for title in intent.similar_to:
        parts.append(f"like {title}")
    return ", ".join(parts) or "movies"


def build_conversational_reply(
    intent: QueryIntent, results: list[RankedMovie]
) -> str:
    """Short deterministic summary of the picks (grounded in real intent).

    Deliberately template-based: the per-movie LLM explanations carry the
    nuance, so the summary stays honest and cheap.
    """
    if not results:
        return (
            "I could not find matching movies in the catalog for that yet. "
            "Try widening the request — fewer exclusions or a broader genre."
        )
    bits: list[str] = []
    if intent.genres_include:
        bits.append(", ".join(intent.genres_include))
    if intent.themes:
        bits.append("themes like " + ", ".join(intent.themes[:3]))
    if intent.mood:
        bits.append(f"a {intent.mood} mood")
    focus = f" ({'; '.join(bits)})" if bits else ""
    top_title = results[0].movie.title or "the top pick"
    return (
        f"Here are {len(results)} picks{focus}. Top pick: {top_title} — "
        "why each one fits is noted under it."
    )[:1000]


async def _load_history(session: AsyncSession, session_id: uuid.UUID) -> list[dict[str, str]]:
    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    )
    rows = (await session.execute(statement)).scalars().all()
    return [{"role": message.role, "content": message.content} for message in rows]


async def _add_message(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    role: str,
    content: str,
    intent_payload: dict[str, Any] | None = None,
    result_movie_ids: list[str] | None = None,
) -> None:
    """Append a turn. ``created_at`` is set client-side so a user message and
    its assistant reply order deterministically even within one transaction
    (the DB server_default remains as a fallback)."""
    session.add(
        ChatMessage(
            id=uuid.uuid4(),
            session_id=session_id,
            role=role,
            content=content,
            intent=intent_payload,
            result_movie_ids=result_movie_ids,
            created_at=datetime.datetime.now(datetime.UTC),
        )
    )


async def handle_chat_message(
    session: AsyncSession,
    *,
    message: str,
    session_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    result_limit: int = 5,
    parse_query_fn: IntentFn,
    embed_query_fn: EmbedFn,
    hybrid_search_fn: SearchFn,
    explain_fn: ExplainFn,
) -> ChatTurnResponse:
    """Run one conversation turn end to end and persist it."""
    # 1) Load or create the conversation session.
    chat_session: ChatSession | None = None
    if session_id is not None:
        chat_session = await session.get(ChatSession, session_id)
        if chat_session is None:
            raise LookupError(f"chat session {session_id} not found")
    if chat_session is None:
        chat_session = ChatSession(id=uuid.uuid4(), user_id=user_id)
        session.add(chat_session)
    active_session_id = chat_session.id

    history = await _load_history(session, active_session_id)
    await _add_message(session, active_session_id, role="user", content=message)

    # 2) Intent with conversational context.
    try:
        intent = await parse_query_fn(message, history)
    except AmbiguousQueryError as ambiguous:
        # 3) Clarification IS the reply — no search yet.
        question = ambiguous.question
        await _add_message(session, active_session_id, role="assistant", content=question)
        await session.commit()
        logger.info("session %s: clarifying question returned", active_session_id)
        return ChatTurnResponse(
            session_id=active_session_id,
            reply=question,
            asked_clarifying_question=True,
            intent=None,
            results=[],
        )

    # 4) Search + grounded explanations for the resolved intent.
    filters = _filters_from_intent(intent)
    query_embedding = await embed_query_fn(render_intent_text(intent))
    ranked = await hybrid_search_fn(
        session, query_embedding, filters, user_id, result_limit
    )
    taste_context = await build_user_taste_context(session, user_id)
    explanations = [
        await explain_fn(item.movie, intent, taste_context) for item in ranked
    ]

    reply = build_conversational_reply(intent, ranked)

    # 5) Persist the assistant turn with the resolved intent + shown results.
    await _add_message(
        session,
        active_session_id,
        role="assistant",
        content=reply,
        intent_payload=intent.model_dump(mode="json"),
        result_movie_ids=[str(item.movie.id) for item in ranked],
    )
    await session.commit()
    logger.info(
        "session %s: %d results for intent (mood=%s, genres=%s)",
        active_session_id,
        len(ranked),
        intent.mood,
        intent.genres_include,
    )

    return ChatTurnResponse(
        session_id=active_session_id,
        reply=reply,
        asked_clarifying_question=False,
        intent=intent.model_dump(mode="json"),
        results=[
            ChatMovieOut(
                movie=MovieOut.model_validate(item.movie),
                final_score=item.final_score,
                explanation=explanation.text,
                matched_attributes=explanation.matched_attributes,
            )
            for item, explanation in zip(ranked, explanations, strict=True)
        ],
    )
