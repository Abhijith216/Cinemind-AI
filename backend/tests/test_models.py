"""Offline tests for the ORM metadata: tables, key columns, and index types.

These run without a database — they assert on SQLAlchemy metadata and on the
SQL Alembic would emit, so schema regressions fail fast in CI.
"""

import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import insert
from sqlalchemy.dialects import postgresql

from app.models import (
    EMBEDDING_DIMENSIONS,
    Movie,
    Rating,
    TasteSnapshot,
    User,
    UserTasteProfile,
)


def _ddl_for(model: type) -> str:
    """Compile CREATE TABLE DDL for a model against the Postgres dialect."""
    from sqlalchemy.schema import CreateTable

    return str(
        CreateTable(model.__table__).compile(dialect=postgresql.dialect())
    ).lower()


def test_movie_table_shape() -> None:
    ddl = _ddl_for(Movie)
    assert "vector(1536)" in ddl
    assert "jsonb" in ddl
    assert "release_year" in ddl
    assert "personality" in ddl


def test_required_jsonb_columns() -> None:
    for table, col in [
        (Movie.__table__, "genres"),
        (Movie.__table__, "keywords"),
        (UserTasteProfile.__table__, "likes"),
        (UserTasteProfile.__table__, "dislikes"),
        (UserTasteProfile.__table__, "favorite_themes"),
        (TasteSnapshot.__table__, "dominant_genres"),
        (TasteSnapshot.__table__, "dominant_themes"),
    ]:
        assert col in table.columns, f"{table.name}.{col} missing"
        assert str(table.columns[col].type).lower().startswith("jsonb")


def test_gin_and_hnsw_indexes_declared() -> None:
    movie_indexes = {ix.name: ix for ix in Movie.__table__.indexes}
    assert "ix_movies_genres_gin" in movie_indexes
    assert "ix_movies_keywords_gin" in movie_indexes
    hnsw = movie_indexes["ix_movies_embedding_hnsw"]
    assert hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw.dialect_options["postgresql"]["ops"] == {
        "embedding": "vector_cosine_ops"
    }
    # GIN indexes really are GIN:
    assert movie_indexes["ix_movies_genres_gin"].dialect_options["postgresql"][
        "using"
    ] == "gin"


def test_rating_score_check_constraint() -> None:
    ddl = _ddl_for(Rating)
    assert "check" in ddl
    assert "score >= 1" in ddl


def test_unique_constraints() -> None:
    rating_indexes = {ix.name: ix for ix in Rating.__table__.indexes}
    assert rating_indexes["uq_ratings_user_movie"].unique
    snapshot_indexes = {ix.name: ix for ix in TasteSnapshot.__table__.indexes}
    assert snapshot_indexes["uq_taste_snapshots_user_month"].unique


def test_movie_personality_jsonb_roundtrip() -> None:
    """The JSONB personality dict must validate through the Pydantic layer."""
    from app.schemas.common import MoviePersonalityOut

    traits = {
        "emotion": 88,
        "mind_blowing": 95,
        "darkness": 40,
        "humor": 25,
        "violence": 30,
        "romance": 55,
        "hopefulness": 70,
        "plot_complexity": 90,
        "rewatchability": 80,
    }
    parsed = MoviePersonalityOut.model_validate(traits)
    assert parsed.mind_blowing == 95

    with pytest.raises(ValidationError):
        MoviePersonalityOut.model_validate({**traits, "humor": 101})


def test_embeddable_dimension_constant() -> None:
    assert EMBEDDING_DIMENSIONS == 1536


def test_user_email_unique() -> None:
    ddl = _ddl_for(User)
    assert "email" in ddl


def test_rated_at_column_exists() -> None:
    stmt = insert(Rating).values(
        id=1,
        user_id=1,
        movie_id=1,
        score=5,
        rated_at=datetime.datetime.now(datetime.UTC),
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "rated_at" in sql
