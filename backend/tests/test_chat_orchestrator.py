"""Tests for Module 8 chat orchestration (offline: fake pipeline + DB).

The required product-spec flow is covered end to end:
    "surprise me" -> clarifying question -> "think" -> "how much time"
    -> final ranked + explained results.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db_session
from app.main import app
from app.models import ChatMessage, Movie
from app.schemas.chat import ChatTurnResponse
from app.schemas.explanation import Explanation, MatchedAttributes
from app.schemas.intent import QueryIntent
from app.schemas.retrieval import SearchFilters
from app.services.chat_orchestrator import (
    _filters_from_intent,
    build_conversational_reply,
    handle_chat_message,
    render_intent_text,
)
from app.services.query_understanding import AmbiguousQueryError
from app.services.retrieval import RankedMovie

# --- fakes ---------------------------------------------------------------------


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


class FakeDBSession:
    """get/execute/add/commit double; execute() returns all chat messages.

    Single-session tests only, so the history select returns every persisted
    ChatMessage ordered by created_at (stable sort keeps user-before-reply).
    """

    def __init__(self) -> None:
        self.objects: dict[tuple[type, Any], Any] = {}
        self.added: list[Any] = []
        self.commits = 0

    def register(self, *objects: Any) -> None:
        for obj in objects:
            key = obj.id if hasattr(obj, "id") else obj.user_id
            self.objects[(type(obj), key)] = obj

    async def get(self, model: Any, key: Any) -> Any:
        found = self.objects.get((model, key))
        if found is not None:
            return found
        # Real identity map: objects added this session are gettable.
        for obj in self.added:
            if isinstance(obj, model) and getattr(obj, "id", None) == key:
                return obj
        return None

    async def execute(self, _statement: Any) -> FakeResult:
        messages = [
            obj
            for obj in (*self.objects.values(), *self.added)
            if isinstance(obj, ChatMessage)
        ]
        messages.sort(key=lambda message: message.created_at)
        return FakeResult(messages)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1


def _movie(index: int = 1, title: str | None = None) -> Movie:
    return Movie(
        id=uuid.uuid4(),
        tmdb_id=100 + index,
        title=title or f"Wormhole Protocol {index}",
        overview="A mind-bending drama.",
        release_year=2014,
        runtime=118,
        genres=["Science Fiction", "Drama"],
        keywords=["time", "father-daughter relationship"],
        language="en",
        vote_average=8.0,
        vote_count=2000,
        popularity=95.0,
        personality={
            "emotion": 85, "mind_blowing": 90, "darkness": 40, "humor": 20,
            "violence": 25, "romance": 25, "hopefulness": 55,
            "plot_complexity": 85, "rewatchability": 75,
        },
    )


def _ranked(movie: Movie, score: float = 0.8) -> RankedMovie:
    return RankedMovie(
        movie=movie,
        final_score=score,
        semantic_similarity=0.7,
        user_history_match=0.0,
        genre_similarity=0.5,
        normalized_rating=0.9,
        normalized_popularity=0.8,
    )


def _explanation(movie: Movie, intent: QueryIntent | None) -> Explanation:
    return Explanation(
        movie_id=str(movie.id),
        movie_title=movie.title or "",
        text=f"{movie.title} matches the mind-bending, emotional tone you asked for.",
        matched_attributes=MatchedAttributes(
            genres=["Science Fiction"], themes=["time"]
        ),
        source="template",
        query_intent=intent,
    )


class ScriptedParser:
    """parse_query double: replies keyed on message text, records history."""

    def __init__(self) -> None:
        self.history_seen: list[list[dict[str, str]]] = []
        self.clarifications: dict[str, str] = {
            "surprise me": (
                "Are you in the mood for a mind-bending thriller, something "
                "heartfelt, or light and funny?"
            ),
            "think": "How much time do you have for this movie?",
        }
        self.intents: dict[str, dict[str, Any]] = {
            "think": {
                "mood": "tense",
                "ending_type": "mind-blowing twist",
                "themes": ["mind-bending", "puzzle"],
            },
            "about two hours": {
                "mood": "tense",
                "ending_type": "mind-blowing twist",
                "themes": ["mind-bending", "puzzle"],
                "runtime_max": 120,
                "genres_include": ["Science Fiction", "Thriller"],
            },
        }

    async def __call__(
        self, user_text: str, history: list[dict[str, str]]
    ) -> QueryIntent:
        self.history_seen.append(list(history))
        if user_text in self.clarifications:
            raise AmbiguousQueryError(self.clarifications[user_text])
        return QueryIntent.model_validate(
            self.intents.get(user_text, {"themes": ["anything"]})
        )


class RecordingPipeline:
    def __init__(self, movies: list[Movie]) -> None:
        self.embed_texts: list[str] = []
        self.search_calls: list[tuple[str, SearchFilters, int]] = []
        self.movies = movies

    async def embed(self, text: str) -> list[float]:
        self.embed_texts.append(text)
        return [0.1] * 1536

    async def search(
        self,
        _session: Any,
        _embedding: list[float],
        filters: SearchFilters,
        _user_id: uuid.UUID | None,
        limit: int,
    ) -> list[RankedMovie]:
        self.search_calls.append((",".join(filters.genres), filters, limit))
        return [_ranked(movie, 0.9 - index * 0.1) for index, movie in enumerate(self.movies)]

    async def explain(self, movie: Movie, intent: QueryIntent | None, _taste: Any) -> Explanation:
        return _explanation(movie, intent)


def _runner(db: FakeDBSession, parser: ScriptedParser, pipeline: RecordingPipeline):
    async def run(message: str, **kwargs: Any) -> ChatTurnResponse:
        return await handle_chat_message(
            db,
            message=message,
            parse_query_fn=parser,
            embed_query_fn=pipeline.embed,
            hybrid_search_fn=pipeline.search,
            explain_fn=pipeline.explain,
            **kwargs,
        )

    return run


# --- the required flow ------------------------------------------------------------


@pytest.mark.asyncio
async def test_surprise_me_flow_end_to_end() -> None:
    db = FakeDBSession()
    parser = ScriptedParser()
    movies = [_movie(1), _movie(2), _movie(3)]
    pipeline = RecordingPipeline(movies)
    run = _runner(db, parser, pipeline)

    # Turn 1: "surprise me" -> clarifying question, NO search.
    turn1 = await run("surprise me")
    assert turn1.asked_clarifying_question is True
    assert turn1.results == []
    assert turn1.intent is None
    assert "mind-bending thriller" in turn1.reply
    assert pipeline.search_calls == []  # no search until intent resolves
    session_id = turn1.session_id

    # Turn 2: "think" refines the intent but stays under-specified.
    turn2 = await run("think", session_id=session_id)
    assert turn2.session_id == session_id
    assert turn2.asked_clarifying_question is True
    assert turn2.results == []
    assert "time" in turn2.reply
    assert len(parser.history_seen[-1]) == 2  # turn 1's user+assistant messages

    # Turn 3: "about two hours" -> final results, ranked and explained.
    turn3 = await run("about two hours", session_id=session_id, result_limit=3)
    assert turn3.session_id == session_id
    assert turn3.asked_clarifying_question is False
    assert len(turn3.results) == 3
    assert turn3.results[0].final_score > turn3.results[1].final_score
    assert turn3.intent is not None and turn3.intent["runtime_max"] == 120
    assert turn3.results[0].explanation  # grounded sentence present
    assert turn3.results[0].matched_attributes.genres  # structured list present
    # The embedded query text comes from the RESOLVED intent (turn 3's).
    assert "mind-blowing twist" in pipeline.embed_texts[-1]
    # Search saw the intent's genres as hard filters, limited to 3.
    genres, _filters, limit = pipeline.search_calls[-1]
    assert genres == "Science Fiction,Thriller" and limit == 3
    # History by turn 3 contains turn 2's exchange.
    assert len(parser.history_seen[-1]) == 4

    # Persistence: 6 messages (3 user + 3 assistant), with intent + result ids.
    chat_messages = [obj for obj in db.added if isinstance(obj, ChatMessage)]
    assert len(chat_messages) == 6
    assistant_messages = [m for m in chat_messages if m.role == "assistant"]
    final_assistant = assistant_messages[-1]
    assert final_assistant.intent is not None
    assert final_assistant.result_movie_ids == [str(m.id) for m in movies]
    clarification_messages = [
        m for m in assistant_messages[:2] if m.intent is None and m.result_movie_ids is None
    ]
    assert len(clarification_messages) == 2
    assert db.commits == 3


@pytest.mark.asyncio
async def test_unknown_session_id_raises_lookup_error() -> None:
    db = FakeDBSession()
    parser = ScriptedParser()
    pipeline = RecordingPipeline([_movie()])

    with pytest.raises(LookupError, match="not found"):
        await handle_chat_message(
            db,
            message="hello",
            session_id=uuid.uuid4(),
            parse_query_fn=parser,
            embed_query_fn=pipeline.embed,
            hybrid_search_fn=pipeline.search,
            explain_fn=pipeline.explain,
        )


# --- intent → filters / query text / reply ---------------------------------------


def test_filters_from_intent_maps_decade_and_recent() -> None:
    nineties = _filters_from_intent(
        QueryIntent.model_validate({"time_period": "1990s"})
    )
    assert nineties.min_release_year == 1990 and nineties.max_release_year == 1999

    recent = _filters_from_intent(
        QueryIntent.model_validate({"time_period": "recent"})
    )
    assert recent.min_release_year == 2020 and recent.max_release_year is None

    empty = _filters_from_intent(QueryIntent())
    assert empty.min_release_year is None and empty.max_release_year is None


def test_filters_from_intent_ignores_far_future_decades() -> None:
    filters = _filters_from_intent(
        QueryIntent.model_validate({"time_period": "3000s"})
    )
    assert filters.min_release_year is None


def test_render_intent_text_prioritizes_intent_fields() -> None:
    intent = QueryIntent.model_validate(
        {
            "mood": "tense",
            "ending_type": "mind-blowing twist",
            "themes": ["puzzle"],
            "genres_include": ["Science Fiction"],
            "similar_to": ["Arrival"],
        }
    )
    text = render_intent_text(intent)
    assert text == "tense, mind-blowing twist, puzzle, Science Fiction, like Arrival"


def test_render_intent_text_never_empty() -> None:
    assert render_intent_text(QueryIntent()) == "movies"


def test_conversational_reply_mentions_top_pick_and_focus() -> None:
    intent = QueryIntent.model_validate({"mood": "tense", "themes": ["puzzle"]})
    reply = build_conversational_reply(intent, [_ranked(_movie())])
    assert "Wormhole Protocol 1" in reply
    assert "tense" in reply and "puzzle" in reply


def test_conversational_reply_honest_when_nothing_found() -> None:
    reply = build_conversational_reply(QueryIntent(), [])
    assert "could not find" in reply


# --- endpoint wiring ----------------------------------------------------------------


def test_chat_route_is_registered() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    assert "/api/chat/message" in schema["paths"]


@pytest.fixture
def api() -> Any:
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_endpoint_maps_unknown_session_to_404(api: Any) -> None:
    db = FakeDBSession()

    async def _yield_session() -> AsyncGenerator[FakeDBSession, None]:
        yield db

    app.dependency_overrides[get_db_session] = _yield_session

    response = api.post(
        "/api/chat/message",
        json={"message": "hi", "session_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
