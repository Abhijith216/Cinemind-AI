"""Recommendation-graph schemas — the structured "why" for one movie."""

import uuid

from pydantic import BaseModel, Field


class GraphMovie(BaseModel):
    """A node in the recommendation graph."""

    id: uuid.UUID
    title: str
    release_year: int | None = None
    poster_path: str | None = None
    score: float | None = Field(
        default=None, description="The user's rating (rated movies only)."
    )


class GraphEdge(BaseModel):
    """One rated movie's concrete overlaps with the target movie."""

    to_movie_id: uuid.UUID
    shared_genres: list[str] = Field(default_factory=list)
    shared_keywords: list[str] = Field(default_factory=list)


class RecommendationGraph(BaseModel):
    """The movie ↔ shared attributes ↔ your rated movies graph."""

    movie: GraphMovie
    rated_movies: list[GraphMovie] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    note: str | None = Field(
        default=None,
        description="Set when the graph has no user grounding (anonymous or no ratings).",
    )
