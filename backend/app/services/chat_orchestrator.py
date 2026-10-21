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
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update
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
IntentSearchFn = Callable[
    [AsyncSession, QueryIntent, uuid.UUID | None, int],
    Awaitable[list[RankedMovie]],
]


def release_window(period: str | None) -> tuple[int | None, int | None]:
    if not period:
        return None, None
    text = period.strip().lower()
    if text in {"recent", "modern", "latest", "new"}:
        return datetime.date.today().year - 5, None
    decade = re.fullmatch(r"(\d{4})s", text)
    if decade and 1880 <= int(decade[1]) <= 2090:
        return int(decade[1]), int(decade[1]) + 9
    years = re.fullmatch(r"(?:from\s+)?(\d{4})\s*(?:-|–|to|and)\s*(\d{4})", text)
    if years and 1888 <= int(years[1]) <= int(years[2]) <= 2099:
        return int(years[1]), int(years[2])
    if re.fullmatch(r"\d{4}", text) and 1888 <= int(text) <= 2099:
        return int(text), int(text)
    return None, None


def constraint_notices(intent: QueryIntent) -> list[str]:
    notices = []
    if intent.pace:
        notices.append(
            "Pacing isn't verified for these films, so I couldn't apply your pace preference."
        )
    if intent.violence_tolerance:
        notices.append(
            "Scene-level violence isn't verified. These picks aren't guaranteed to meet your "
            "violence preference; check a content guide before watching."
        )
    if intent.ending_type:
        notices.append("Ending preferences use theme matches; the films' endings aren't verified.")
    if intent.time_period and release_window(intent.time_period) == (None, None):
        notices.append("I couldn't apply that release period. Try a year, decade, or year range.")
    return notices


def _filters_from_intent(intent: QueryIntent) -> SearchFilters:
    """Map intent fields onto the hard SQL filters retrieval supports.

    ``genres_include`` become genre filters; ``time_period`` like "1990s"
    (or "recent") becomes a release-year window. Runtime and exclusions
    are enforced during retrieval.
    """
    year_min, year_max = release_window(intent.time_period)
    return SearchFilters(
        genres=list(intent.genres_include),
        min_release_year=year_min,
        max_release_year=year_max,
        max_runtime=intent.runtime_max,
        excluded_genres=list(intent.genres_exclude),
        excluded_themes=list(intent.themes_exclude),
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


def build_conversational_reply(intent: QueryIntent, results: list[RankedMovie]) -> str:
    """Short deterministic summary of the picks (grounded in real intent).

    Deliberately template-based: the per-movie LLM explanations carry the
    nuance, so the summary stays honest and cheap.
    """
    notices = constraint_notices(intent)
    if not results:
        summary = (
            "I could not find matching movies in the catalog for that yet. "
            "Try widening the request — fewer exclusions or a broader genre."
        )
        return "\n\n".join([summary, *notices])
    bits: list[str] = []
    if intent.genres_include:
        bits.append(", ".join(intent.genres_include))
    if intent.themes:
        bits.append("themes like " + ", ".join(intent.themes[:3]))
    if intent.mood:
        bits.append(f"a {intent.mood} mood")
    focus = f" ({'; '.join(bits)})" if bits else ""
    top_title = results[0].movie.title or "the top pick"
    summary = (
        f"Here are {len(results)} picks{focus}. Top pick: {top_title} — "
        "why each one fits is noted under it."
    )[:600]
    return "\n\n".join([summary, *notices])


async def _load_history(session: AsyncSession, session_id: uuid.UUID) -> list[dict[str, str]]:
    statement = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(12)
    )
    rows = (await session.execute(statement)).scalars().all()
    return [
        {
            "role": message.role,
            "content": message.content
            + (
                "\nResolved movie request: " + json.dumps(message.intent, ensure_ascii=False)
                if message.intent
                else ""
            ),
        }
        for message in reversed(rows)
    ]


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
    if role == "assistant":
        await session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=datetime.datetime.now(datetime.UTC))
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
    intent_search_fn: IntentSearchFn | None = None,
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
    active_session_id = chat_session.id

    history = await _load_history(session, active_session_id) if session_id is not None else []
    # Release the read transaction while waiting on the external AI provider.
    # Do not flush a new session or user message until interpretation succeeds.
    await session.rollback()

    # 2) Intent with conversational context.
    try:
        intent = await parse_query_fn(message, history)
    except AmbiguousQueryError as ambiguous:
        # 3) Clarification IS the reply — no search yet.
        question = ambiguous.question
        if session_id is None:
            session.add(chat_session)
        await _add_message(session, active_session_id, role="user", content=message)
        await _add_message(session, active_session_id, role="assistant", content=question)
        await session.commit()
        logger.info("Chat clarification persisted")
        return ChatTurnResponse(
            session_id=active_session_id,
            reply=question,
            asked_clarifying_question=True,
            intent=None,
            results=[],
        )

    if session_id is None:
        session.add(chat_session)
    await _add_message(session, active_session_id, role="user", content=message)
    logger.info("Chat intent interpreted with %d reference titles", len(intent.similar_to))
    # 4) Search + grounded explanations for the resolved intent.
    filters = _filters_from_intent(intent)
    if intent_search_fn is not None:
        ranked = await intent_search_fn(session, intent, user_id, result_limit)
    else:
        query_embedding = await embed_query_fn(render_intent_text(intent))
        ranked = await hybrid_search_fn(session, query_embedding, filters, user_id, result_limit)
    taste_context = await build_user_taste_context(session, user_id)
    logger.info("Chat catalog returned %d movies", len(ranked))
    explanations = [await explain_fn(item.movie, intent, taste_context) for item in ranked]

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
        "Chat response persisted with %d results",
        len(ranked),
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
