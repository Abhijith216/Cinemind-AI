"""Chat endpoint (Module 8) — multi-turn conversations over the pipeline."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import ensure_database_connection, get_db_session
from app.core.rate_limit import chat_rate_limit
from app.core.security import decode_access_token
from app.models import ChatMessage, ChatSession, Movie
from app.schemas.chat import (
    ChatHistoryOut,
    ChatMessageRequest,
    ChatMovieOut,
    ChatSessionOut,
    ChatSessionSummary,
    ChatStoredMessage,
    ChatTurnResponse,
)
from app.schemas.common import MovieOut
from app.schemas.intent import QueryIntent
from app.services.chat_orchestrator import handle_chat_message
from app.services.chat_search import explain_catalog_match, search_intent_catalog
from app.services.explain import build_user_taste_context
from app.services.llm_client import LLMError
from app.services.query_understanding import parse_query
from app.services.retrieval import embed_query, hybrid_search

logger = logging.getLogger("app.api.chat")

router = APIRouter(tags=["chat"])
_bearer = HTTPBearer(auto_error=False)


async def chat_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> uuid.UUID | None:
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Sign in again to continue this chat") from exc


async def authorized_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    actor: uuid.UUID | None,
) -> ChatSession:
    chat_session = await db.get(ChatSession, session_id)
    if chat_session is None or (chat_session.user_id is not None and chat_session.user_id != actor):
        raise HTTPException(status_code=404, detail="Chat session not found")
    # For anonymous chats the random UUID is an unlisted conversation capability.
    # Account-owned chats additionally require the matching authenticated user.
    return chat_session


@router.post("/chat/message", response_model=ChatTurnResponse)
async def post_chat_message(
    payload: ChatMessageRequest,
    _rate_limit: chat_rate_limit,
    db: AsyncSession = Depends(get_db_session),
    actor: uuid.UUID | None = Depends(chat_actor),
) -> ChatTurnResponse:
    """One conversational turn: intent → (clarification | search + explain).

    Pass a ``session_id`` from a previous response to continue a
    conversation; omit it to start a new one. Unknown session ids are a 404.
    """
    if payload.user_id is not None and payload.user_id != actor:
        raise HTTPException(status_code=403, detail="You can only use your own taste profile")
    try:
        async with asyncio.timeout(40):
            await ensure_database_connection(db)
            if payload.session_id is not None:
                existing_chat = await authorized_session(db, payload.session_id, actor)
                if actor is not None and existing_chat.user_id is None:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "This conversation was started anonymously. "
                            "Retry to start an account chat with this request."
                        ),
                    )
            return await handle_chat_message(
                db,
                message=payload.message,
                session_id=payload.session_id,
                user_id=actor,
                result_limit=payload.result_limit,
                parse_query_fn=parse_query,
                embed_query_fn=embed_query,
                hybrid_search_fn=hybrid_search,
                explain_fn=explain_catalog_match,
                intent_search_fn=search_intent_catalog,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LLMError as exc:
        # Ambiguous-query is a normal turn (handled inside the orchestrator);
        # reaching this handler means the LLM provider itself failed.
        logger.warning(
            "Chat provider unavailable (%s, category=%s, HTTP status %s)",
            type(exc).__name__,
            exc.category,
            exc.status_code,
        )
        raise HTTPException(
            status_code=503,
            detail="Chat is temporarily unavailable — the language model did not respond.",
        ) from exc
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("Chat request unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Chat is temporarily unavailable. Please try again."
        ) from exc


@router.get("/chat/sessions", response_model=ChatHistoryOut)
async def list_chat_sessions(
    offset: int = Query(default=0, ge=0, le=1000000),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db_session),
    actor: uuid.UUID | None = Depends(chat_actor),
) -> ChatHistoryOut:
    if actor is None:
        raise HTTPException(status_code=401, detail="Sign in to see your saved chats")
    total = (
        await db.execute(select(func.count(ChatSession.id)).where(ChatSession.user_id == actor))
    ).scalar_one()
    title = (
        select(ChatMessage.content)
        .where(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at, ChatMessage.id)
        .limit(1)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(ChatSession, title.label("title"))
            .where(ChatSession.user_id == actor)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return ChatHistoryOut(
        items=[
            ChatSessionSummary(
                id=chat.id, title=(text or "New chat")[:120], updated_at=chat.updated_at
            )
            for chat, text in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete("/chat/sessions/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: uuid.UUID | None = Depends(chat_actor),
) -> Response:
    chat = await authorized_session(db, session_id, actor)
    await db.delete(chat)
    await db.commit()
    return Response(status_code=204)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionOut)
async def get_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
    actor: uuid.UUID | None = Depends(chat_actor),
) -> ChatSessionOut:
    """Replay a conversation: session metadata plus every stored turn.

    Order is chronological (created_at, then insertion); assistant turns
    carry the intent payload and result ids that were shown.
    """
    await ensure_database_connection(db)
    chat_session = await authorized_session(db, session_id, actor)
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    movie_ids = {
        uuid.UUID(str(movie_id))
        for message in rows
        for movie_id in (message.result_movie_ids or [])
    }
    movies = (
        list((await db.execute(select(Movie).where(Movie.id.in_(movie_ids)))).scalars().all())
        if movie_ids
        else []
    )
    by_id = {str(movie.id): movie for movie in movies}
    taste = await build_user_taste_context(db, chat_session.user_id) if movies else None
    stored = []
    for message in rows:
        intent = QueryIntent.model_validate(message.intent) if message.intent else None
        results = []
        for position, movie_id in enumerate(message.result_movie_ids or []):
            movie = by_id.get(str(movie_id))
            if movie is None:
                continue
            explanation = await explain_catalog_match(movie, intent, taste)
            results.append(
                ChatMovieOut(
                    movie=MovieOut.model_validate(movie),
                    final_score=1 / (position + 1),
                    explanation=explanation.text,
                    matched_attributes=explanation.matched_attributes,
                )
            )
        stored.append(
            ChatStoredMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                intent=message.intent,
                result_movie_ids=message.result_movie_ids,
                created_at=message.created_at,
                results=results,
            )
        )
    return ChatSessionOut(
        id=chat_session.id,
        user_id=chat_session.user_id,
        created_at=chat_session.created_at,
        messages=stored,
    )
