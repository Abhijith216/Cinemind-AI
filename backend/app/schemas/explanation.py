"""Explanation schemas for Module 5 (grounded recommendation explanations).

``Explanation`` carries BOTH representations the frontend needs:
- ``text``  — the 1-3 sentence explanation (card view)
- ``matched_attributes`` — the structured overlap list (graph view)

``matched_attributes`` is the source of truth for grounding: it is computed
deterministically from real data before the LLM is involved, and the
sentence is checked against it.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.intent import QueryIntent


class MatchKind(StrEnum):
    """Which real attribute produced the match."""

    genre = "genre"
    theme = "theme"  # shared keywords or requested themes
    personality = "personality"  # trait alignment with loved movies
    intent = "intent"  # mood / pace / ending type from the parsed query
    rating = "rating"  # loved movies the user rated highly


class MatchedAttribute(BaseModel):
    """One concrete, verifiable overlap between a movie and the request."""

    kind: MatchKind
    label: str  # e.g. "Science Fiction", "time", "mind-blowing"
    detail: str | None = None  # e.g. "you rated Interstellar 10/10"


class MatchedAttributes(BaseModel):
    """All verified overlaps for one recommendation."""

    genres: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    personality_traits: list[str] = Field(default_factory=list)
    intent_matches: list[str] = Field(default_factory=list)
    loved_movie_overlaps: list[MatchedAttribute] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (
            self.genres
            or self.themes
            or self.personality_traits
            or self.intent_matches
            or self.loved_movie_overlaps
        )


class Explanation(BaseModel):
    """Grounded explanation: sentence + structured attributes."""

    movie_id: str
    movie_title: str
    text: str
    matched_attributes: MatchedAttributes
    source: str  # "llm" | "template"
    query_intent: QueryIntent | None = None


class LovedMovie(BaseModel):
    """A movie the user rated highly (used for taste grounding)."""

    title: str
    score: float
    genres: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    personality: dict[str, float] | None = None


class UserTasteContext(BaseModel):
    """Everything explain.py needs to know about the user's taste."""

    loved_movies: list[LovedMovie] = Field(default_factory=list)

    @property
    def loved_genres(self) -> list[str]:
        seen: list[str] = []
        for movie in self.loved_movies:
            for genre in movie.genres:
                if genre.lower() not in [s.lower() for s in seen]:
                    seen.append(genre)
        return seen

    @property
    def loved_keywords(self) -> list[str]:
        seen: list[str] = []
        for movie in self.loved_movies:
            for keyword in movie.keywords:
                if keyword.lower() not in [s.lower() for s in seen]:
                    seen.append(keyword)
        return seen


class ExplanationReply(BaseModel):
    """API response wrapping one or more explanations."""

    explanations: list[Explanation]
