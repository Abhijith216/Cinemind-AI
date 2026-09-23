"""Tests for Module 5 explainable recommendations (offline, no network/DB).

Core guarantee under test: explanations may only cite attributes that
actually exist in the movie/intent/taste data.
"""

from typing import Any
from uuid import uuid4

import pytest

from app.schemas.explanation import LovedMovie, UserTasteContext
from app.schemas.intent import QueryIntent
from app.services.explain import (
    _is_grounded,
    build_user_taste_context,
    compute_matched_attributes,
    explain_recommendation,
    template_explanation,
)


def _movie(
    *,
    title: str = "Arrival",
    genres: list[str] | None = None,
    keywords: list[str] | None = None,
    personality: dict[str, float] | None = None,
) -> Any:
    movie = MovieLike(
        title=title,
        genres=genres or [],
        keywords=keywords or [],
        personality=personality,
    )
    return movie


class MovieLike:
    """Movie-shaped test double (matches ExplainableMovie protocol)."""

    def __init__(
        self,
        *,
        title: str,
        genres: list[str],
        keywords: list[str],
        personality: dict[str, float] | None,
    ) -> None:
        self.id = uuid4()
        self.title = title
        self.genres = genres
        self.keywords = keywords
        self.personality = personality


ARRIVAL_PERSONALITY = {
    "emotion": 85,
    "mind_blowing": 90,
    "darkness": 35,
    "humor": 15,
    "violence": 10,
    "romance": 20,
    "hopefulness": 55,
    "plot_complexity": 85,
    "rewatchability": 65,
}


def _arrival() -> Any:
    return _movie(
        title="Arrival",
        genres=["Science Fiction", "Drama", "Mystery"],
        keywords=["first contact", "time", "language", "alien communication"],
        personality=ARRIVAL_PERSONALITY,
    )


def _interstellar_intent() -> QueryIntent:
    return QueryIntent.model_validate(
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


def _taste_context() -> UserTasteContext:
    return UserTasteContext(
        loved_movies=[
            LovedMovie(
                title="Interstellar",
                score=10,
                genres=["Science Fiction", "Drama", "Adventure"],
                keywords=["time", "father-daughter relationship", "space"],
                personality=dict(ARRIVAL_PERSONALITY, mind_blowing=95, emotion=88),
            ),
            LovedMovie(
                title="Blade Runner 2049",
                score=9,
                genres=["Science Fiction", "Drama"],
                keywords=["artificial intelligence", "future", "identity"],
                personality=dict(ARRIVAL_PERSONALITY, mind_blowing=80),
            ),
        ]
    )


# --- compute_matched_attributes -------------------------------------------------


def test_shared_genres_and_themes_are_found() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), None)

    assert "Science Fiction" in matched.genres
    assert "Drama" in matched.genres
    assert "time" in matched.themes  # from intent themes ∩ movie keywords


def test_loved_movie_overlaps_cite_real_shared_attributes() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), _taste_context())

    labels = " ".join(overlap.label for overlap in matched.loved_movie_overlaps)
    assert "Interstellar" in labels and "Blade Runner 2049" in labels
    interstellar = next(
        o for o in matched.loved_movie_overlaps if "Interstellar" in o.label
    )
    assert "time" in interstellar.detail.lower()


def test_personality_traits_only_when_loved_scores_are_high() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), _taste_context())

    assert "mind_blowing" in matched.personality_traits
    assert "emotion" in matched.personality_traits
    # humor is 15 everywhere → must never be cited:
    assert "humor" not in matched.personality_traits


def test_intent_traits_come_from_real_personality_scores() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), None)

    assert "mind blowing tone" in matched.intent_matches
    assert "emotional core" in matched.intent_matches
    assert "mind_blowing" in matched.personality_traits


def test_no_matches_when_movie_has_nothing_in_common() -> None:
    slasher = _movie(
        title="Some Slasher",
        genres=["Horror"],
        keywords=["gore", "camp"],
        personality={"emotion": 10, "mind_blowing": 10, "humor": 5, "darkness": 90},
    )
    matched = compute_matched_attributes(slasher, _interstellar_intent(), _taste_context())

    assert matched.is_empty()


# --- template explanation ---------------------------------------------------------


def test_template_uses_only_matched_attributes() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), _taste_context())
    text = template_explanation(matched, "Arrival")

    assert "Arrival" in text
    assert "Science Fiction" in text
    assert "time" in text
    assert "Interstellar" in text  # loved overlap cited with detail
    # Nothing invented:
    assert "Horror" not in text
    assert "comedy" not in text.lower()


def test_template_honest_when_nothing_matches() -> None:
    matched = compute_matched_attributes(_movie(title="Mystery Box"), None, None)
    text = template_explanation(matched, "Mystery Box")
    assert "could not verify" in text


# --- grounding check ----------------------------------------------------------------


def test_grounding_check_rejects_unlisted_attributes() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), None)
    ungrounded = "Arrival is a Science Fiction film with stunning robotics."  # robotics ∉ matched
    assert not _is_grounded(ungrounded, matched, "Arrival")


def test_grounding_check_accepts_listed_attributes() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), None)
    grounded = (
        "Arrival is a Science Fiction, Drama film that matches your ask for "
        "mind blowing tone."
    )
    assert _is_grounded(grounded, matched, "Arrival")


def test_grounding_check_rejects_negation_constructions() -> None:
    matched = compute_matched_attributes(_arrival(), _interstellar_intent(), None)
    sneaky = "Arrival is a Science Fiction film, despite lacking war themes, it delivers."
    assert not _is_grounded(sneaky, matched, "Arrival")


# --- explain_recommendation end-to-end ------------------------------------------------


@pytest.mark.asyncio
async def test_llm_path_returns_grounded_sentence() -> None:
    calls: list[str] = []

    async def fake_llm(prompt: str, *, system_prompt: str) -> str:
        calls.append(prompt)
        return (
            "Arrival is a Science Fiction, Drama film about first contact and time, "
            "matching your ask for emotional core and mind blowing tone."
        )

    explanation = await explain_recommendation(
        _arrival(),
        _interstellar_intent(),
        _taste_context(),
        llm_caller=fake_llm,
    )

    assert explanation.source == "llm"
    assert "Arrival" in explanation.text
    assert "first contact" in explanation.text  # real keyword from the movie
    assert explanation.matched_attributes.genres  # structured list present
    assert "robot" not in explanation.text.lower()
    # The prompt only ever contained verified attributes:
    assert "Verified matching attributes" in calls[0]


@pytest.mark.asyncio
async def test_ungrounded_llm_output_falls_back_to_template() -> None:
    async def lying_llm(prompt: str, *, system_prompt: str) -> str:
        return "Arrival is a hilarious robot comedy with explosive car chases."

    explanation = await explain_recommendation(
        _arrival(),
        _interstellar_intent(),
        _taste_context(),
        llm_caller=lying_llm,
    )

    assert explanation.source == "template"
    assert "comedy" not in explanation.text.lower()
    assert "chases" not in explanation.text.lower()


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_template() -> None:
    async def broken_llm(prompt: str, *, system_prompt: str) -> str:
        raise RuntimeError("LLM down")

    explanation = await explain_recommendation(
        _arrival(),
        _interstellar_intent(),
        None,
        llm_caller=broken_llm,
    )

    assert explanation.source == "template"
    assert explanation.text  # still useful
    assert explanation.matched_attributes.genres  # and still grounded


@pytest.mark.asyncio
async def test_explanation_carries_both_text_and_structured_list() -> None:
    async def ok_llm(prompt: str, *, system_prompt: str) -> str:
        return "Arrival is a Science Fiction, Drama film that explores time."

    explanation = await explain_recommendation(
        _arrival(),
        _interstellar_intent(),
        None,
        llm_caller=ok_llm,
    )

    assert explanation.text  # sentence for the card view
    dumped = explanation.model_dump(mode="json")
    assert dumped["matched_attributes"]["genres"]  # structured list for the graph view


# --- build_user_taste_context ----------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _statement: Any) -> _FakeResult:
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_taste_context_loader_maps_rows() -> None:
    movie = _arrival()
    movie.title = "Interstellar"
    session = _FakeSession([(movie, 10.0)])

    context = await build_user_taste_context(session, uuid4())

    assert context is not None
    assert context.loved_movies[0].score == 10.0
    assert "Science Fiction" in context.loved_movies[0].genres


@pytest.mark.asyncio
async def test_taste_context_loader_none_for_anonymous() -> None:
    assert await build_user_taste_context(_FakeSession([]), None) is None
