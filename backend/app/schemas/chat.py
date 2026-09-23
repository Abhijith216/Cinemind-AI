"""Module 8 schemas — multi-turn chat over the recommendation pipeline."""

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import MovieOut
from app.schemas.explanation import MatchedAttributes


class ChatMessageRequest(BaseModel):
    """Body of POST /chat/message."""

    message: str = Field(min_length=1, max_length=2000)
    session_id: uuid.UUID | None = Field(
        default=None, description="Omit to start a new conversation."
    )
    user_id: uuid.UUID | None = Field(
        default=None, description="Anonymous chats are allowed."
    )
    result_limit: int = Field(default=5, ge=1, le=20)


class ChatMovieOut(BaseModel):
    """One recommendation inside a chat reply: card + graph data."""

    movie: MovieOut
    final_score: float
    explanation: str  # grounded sentence (card view)
    matched_attributes: MatchedAttributes  # structured overlaps (graph view)


class ChatTurnResponse(BaseModel):
    """Response for one chat turn."""

    session_id: uuid.UUID
    reply: str
    asked_clarifying_question: bool
    intent: dict[str, object] | None = None  # resolved intent payload, if any
    results: list[ChatMovieOut] = Field(default_factory=list)
