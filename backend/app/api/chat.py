"""Chat endpoint (Module 8) — multi-turn conversations over the pipeline."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.models import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatMessageRequest,
    ChatSessionOut,
    ChatStoredMessage,
    ChatTurnResponse,
)
from app.services.chat_orchestrator import handle_chat_message
from app.services.explain import explain_recommendation
from app.services.query_understanding import parse_query
from app.services.retrieval import embed_query, hybrid_search

logger = logging.getLogger("app.api.chat")

router = APIRouter(tags=["chat"])


@router.post("/chat/message", response_model=ChatTurnResponse)
async def post_chat_message(
    payload: ChatMessageRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ChatTurnResponse:
    """One conversational turn: intent → (clarification | search + explain).

    Pass a ``session_id`` from a previous response to continue a
    conversation; omit it to start a new one. Unknown session ids are a 404.
    """
    try:
        return await handle_chat_message(
            db,
            message=payload.message,
            session_id=payload.session_id,
            user_id=payload.user_id,
            result_limit=payload.result_limit,
            parse_query_fn=parse_query,
            embed_query_fn=embed_query,
            hybrid_search_fn=hybrid_search,
            explain_fn=explain_recommendation,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionOut)
async def get_chat_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ChatSessionOut:
    """Replay a conversation: session metadata plus every stored turn.

    Order is chronological (created_at, then insertion); assistant turns
    carry the intent payload and result ids that were shown.
    """
    chat_session = await db.get(ChatSession, session_id)
    if chat_session is None:
        raise HTTPException(status_code=404, detail="chat session not found")
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
    ).scalars().all()
    return ChatSessionOut(
        id=chat_session.id,
        user_id=chat_session.user_id,
        created_at=chat_session.created_at,
        messages=[
            ChatStoredMessage(
                id=message.id,
                role=message.role,
                content=message.content,
                intent=message.intent,
                result_movie_ids=message.result_movie_ids,
                created_at=message.created_at,
            )
            for message in rows
        ],
    )
