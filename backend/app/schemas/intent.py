"""Query-intent schema for Module 4 (LLM query understanding).

The intent is exactly the agreed structure:
``{mood, pace, ending_type, themes, genres_include, genres_exclude,
violence_tolerance, time_period, runtime_max, similar_to}`` plus
``clarifying_question`` for ambiguous requests.

One deliberate, documented extension: ``themes_exclude`` — the product's
canonical query ("like Interstellar but not about space") expresses a THEME
exclusion, which the listed fields cannot represent (genres_exclude only
covers genres). Module 3 retrieval consumes ``themes_exclude``.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QueryIntent(BaseModel):
    """Structured interpretation of a free-text movie request."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "mood": "emotional, hopeful",
                    "pace": "moderate",
                    "ending_type": "mind-blowing twist",
                    "themes": ["space exploration", "father-daughter"],
                    "themes_exclude": ["horror"],
                    "genres_include": ["Science Fiction", "Drama"],
                    "genres_exclude": ["Horror"],
                    "violence_tolerance": "low",
                    "similar_to": ["Interstellar"],
                    "time_period": None,
                    "runtime_max": None,
                    "clarifying_question": None,
                }
            ]
        }
    )

    mood: str | None = None
    pace: str | None = None
    ending_type: str | None = None
    themes: list[str] = Field(default_factory=list)
    themes_exclude: list[str] = Field(default_factory=list)
    genres_include: list[str] = Field(default_factory=list)
    genres_exclude: list[str] = Field(default_factory=list)
    violence_tolerance: str | None = Field(
        default=None,
        description="One of: none | low | medium | high",
    )
    similar_to: list[str] = Field(default_factory=list)
    time_period: str | None = None
    runtime_max: int | None = Field(default=None, ge=1)

    # Present only when the request is too ambiguous to interpret.
    clarifying_question: str | None = None

    @field_validator("violence_tolerance")
    @classmethod
    def _validate_violence(cls, value: str | None) -> str | None:
        """Normalize violence_tolerance to the canonical vocabulary."""
        if value is None:
            return None
        allowed = {"none", "low", "medium", "high"}
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise ValueError(
                f"violence_tolerance must be one of {sorted(allowed)}, got {value!r}"
            )
        return normalized

    @field_validator("runtime_max", mode="before")
    @classmethod
    def _coerce_runtime(cls, value: object) -> object:
        """LLMs sometimes emit "150 minutes" — keep the number only."""
        if isinstance(value, str):
            digits = "".join(ch for ch in value if ch.isdigit())
            return int(digits) if digits else None
        return value

    @field_validator("mood", "pace", "ending_type", "time_period", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class IntentRequest(BaseModel):
    """Request body for the /intent endpoint."""

    text: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


class IntentResponse(BaseModel):
    """Response body for the /intent endpoint."""

    intent: QueryIntent
    is_ambiguous: bool
