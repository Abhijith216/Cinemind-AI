"""Postgres full-text discovery without a paid embedding service.

This is intentionally metadata search, not an approximation of an LLM.
Simple mood aliases, exclusions, duration limits and reference titles help
translate common requests into searchable catalog attributes.
"""

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Movie
from app.schemas.common import MovieOut
from app.schemas.intent import QueryIntent
from app.schemas.retrieval import DiscoverMovieOut, SearchFilters

_STOP_WORDS = set(
    "a an the i me my we us you want watch watching movie movies film films "
    "something some like similar to as but and or with about that is are "
    "be it its for of in on please find show give recommend under less than "
    "minutes minute mins hours hour two one three not no without anything "
    "feel feeling tonight really very more would love looking at around".split()
)
_ALIASES = {
    "sci fi": ["science fiction"],
    "sci-fi": ["science fiction"],
    "funny": ["comedy"],
    "comedies": ["comedy"],
    "romantic": ["romance"],
    "scary": ["horror"],
    "animated": ["animation"],
    "mind-bending": ["dream", "time travel", "psychological thriller", "twist"],
    "mind bending": ["dream", "time travel", "psychological thriller", "twist"],
    "mind-blowing": ["time travel", "mystery", "twist"],
    "emotional": ["drama", "family relationships", "loss of loved one"],
    "heartfelt": ["drama", "friendship", "family"],
    "cozy": ["comedy", "family", "friendship"],
    "comfort": ["comedy", "family", "friendship"],
    "witty": ["comedy", "satire"],
    "uplifting": ["friendship", "hope", "comedy"],
    "thrillers": ["thriller"],
}


def _terms(value: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[^\W_]+", value.lower())
        if word not in _STOP_WORDS and not word.isdigit() and len(word) > 1
    ]


def _expand(value: str) -> str:
    for phrase, replacements in _ALIASES.items():
        value = re.sub(r"\b" + re.escape(phrase) + r"\b", " ".join(replacements), value)
    return value


@dataclass
class CatalogQuery:
    terms: list[str]
    excluded: list[str]
    max_runtime: int | None
    reference_title: str | None


def parse_catalog_query(query: str) -> CatalogQuery:
    text = query.lower().strip()
    # Remove duration before reference/exclusion clauses so it cannot become
    # part of a title or a term to exclude.
    max_runtime = None
    duration = re.search(
        r"\b(?:under|less than)\s+(\d+|one|two|three)\s*(hours?|minutes?|mins?)\b",
        text,
    )
    if duration:
        number = {"one": 1, "two": 2, "three": 3}.get(duration[1])
        if number is None:
            number = int(duration[1])
        max_runtime = number * (60 if duration[2].startswith("hour") else 1) - 1
        text = text[: duration.start()] + " " + text[duration.end() :]
    reference = re.search(r"\b(?:like|similar to)\s+(.+?)(?=\s+but\b|\s+with\b|[,;]|$)", text)
    reference_title = reference[1].strip(' ."') if reference else None
    if reference:
        text = text[: reference.start()] + " " + text[reference.end() :]

    excluded: list[str] = []

    def remove_exclusion(match: re.Match[str]) -> str:
        excluded.extend(_terms(_expand(match[1])))
        return " "

    text = re.sub(
        r"\b(?:not(?: about)?|no|without)\s+(.+?)(?=[,;]|\s+but\b|\s+and\b|\s+with\b|$)",
        remove_exclusion,
        text,
    )
    return CatalogQuery(
        terms=list(dict.fromkeys(_terms(_expand(text)))),
        excluded=list(dict.fromkeys(excluded)),
        max_runtime=max_runtime,
        reference_title=reference_title,
    )


def _document() -> Any:
    return Movie.search_document


async def catalog_search(
    session: AsyncSession,
    query: str,
    filters: SearchFilters,
    limit: int,
    *,
    intent: QueryIntent | None = None,
    exclude_rated_by: UUID | None = None,
) -> list[DiscoverMovieOut]:
    parsed = parse_catalog_query(query)
    reference_titles = [parsed.reference_title] if parsed.reference_title else []
    if intent is not None:
        parsed = CatalogQuery(
            terms=_terms(
                _expand(
                    " ".join(
                        filter(
                            None,
                            [
                                intent.mood,
                                intent.ending_type,
                                *intent.themes,
                                *intent.genres_include,
                            ],
                        )
                    )
                )
            ),
            excluded=_terms(" ".join(intent.themes_exclude)),
            max_runtime=intent.runtime_max,
            reference_title=None,
        )
        reference_titles = list(dict.fromkeys(title.strip().lower() for title in intent.similar_to))
    references: list[Movie] = []
    terms = parsed.terms.copy()
    if reference_titles:
        references = list(
            (
                await session.execute(
                    select(Movie).where(
                        func.lower(Movie.title).in_(reference_titles),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not set(reference_titles).issubset({movie.title.lower() for movie in references}):
            return []  # Never pretend an unknown title was resolved.
    for reference in references:
        terms.extend(
            _terms(
                " ".join(
                    str(item)
                    for item in [
                        *(reference.keywords or []),
                        *(reference.genres or []),
                    ]
                )
            )
        )
    # A hard genre filter must narrow the query, not become an OR search term
    # that makes every movie of that genre match an unrelated request.
    if not terms:
        terms = _terms(" ".join(filters.genres))
    terms = list(dict.fromkeys(terms))
    terms = [term for term in terms if term not in parsed.excluded]
    parsed.excluded.extend(_terms(" ".join(filters.excluded_themes)))
    if (
        not terms
        and not parsed.excluded
        and not any(
            [
                filters.excluded_genres,
                filters.genres,
                filters.languages,
                filters.max_runtime,
                filters.min_rating is not None,
                filters.min_release_year,
                filters.max_release_year,
                parsed.max_runtime,
            ]
        )
    ):
        return []

    document = _document()
    # websearch_to_tsquery treats these as words, never executable SQL/tsquery.
    statement = select(Movie)
    if exclude_rated_by is not None:
        from app.services.personalization import unrated_by

        statement = statement.where(unrated_by(exclude_rated_by))
    ordering = []
    if terms:
        search_query = func.websearch_to_tsquery(
            literal_column("'english'::regconfig"), " OR ".join(terms)
        )
        statement = statement.where(document.op("@@")(search_query))
        ordering = [
            (func.lower(Movie.title) == query.lower().strip()).desc(),
            func.ts_rank_cd(document, search_query).desc(),
        ]
    if references:
        statement = statement.where(Movie.id.not_in([movie.id for movie in references]))
    if parsed.excluded:
        excluded_query = func.websearch_to_tsquery(
            literal_column("'english'::regconfig"),
            " OR ".join(parsed.excluded),
        )
        statement = statement.where(~document.op("@@")(excluded_query))
    runtime_limits = [v for v in [filters.max_runtime, parsed.max_runtime] if v is not None]
    if runtime_limits:
        statement = statement.where(Movie.runtime > 0, Movie.runtime <= min(runtime_limits))
    if filters.genres:
        statement = statement.where(or_(*(Movie.genres.contains([g]) for g in filters.genres)))
    for genre in filters.excluded_genres:
        statement = statement.where(~Movie.genres.contains([genre]))
    if filters.languages:
        statement = statement.where(Movie.language.in_(filters.languages))
    if filters.min_rating is not None:
        statement = statement.where(Movie.vote_average >= filters.min_rating)
    if filters.min_release_year is not None:
        statement = statement.where(Movie.release_year >= filters.min_release_year)
    if filters.max_release_year is not None:
        statement = statement.where(Movie.release_year <= filters.max_release_year)
    statement = statement.order_by(
        *ordering,
        Movie.vote_count.desc().nullslast(),
        Movie.id,
    ).limit(limit)
    movies = (await session.execute(statement)).scalars().all()
    results = []
    for movie in movies:
        attributes = [str(value) for value in [*(movie.genres or []), *(movie.keywords or [])]]
        matches = [value for value in attributes if set(_terms(value)) & set(terms)]
        matches = list(dict.fromkeys(matches))[:6]
        if references:
            reference = references[0]
            shared = [
                value
                for value in attributes
                if value
                in [
                    *(reference.genres or []),
                    *(reference.keywords or []),
                ]
            ][:4]
            explanation = (
                f"Shares {', '.join(shared)} with {reference.title}."
                if shared
                else f"Plot and theme search based on {reference.title}."
            )
        elif movie.title.casefold() == query.strip().casefold():
            explanation = "An exact match for the title you searched."
        elif matches:
            explanation = f"Matches your request through {', '.join(matches[:4])}."
        elif not terms:
            explanation = f"A catalog pick excluding {', '.join(parsed.excluded)}."
        else:
            explanation = "A text match in the title or plot summary."
        if runtime_limits and movie.runtime:
            explanation += f" Runs {movie.runtime} minutes."
        results.append(
            DiscoverMovieOut(
                movie=MovieOut.model_validate(movie),
                explanation=explanation,
                matched_terms=matches,
            )
        )
    return results
