"""Module 5 — Explainable recommendation generator.

Anti-hallucination architecture, in order:

1. ``compute_matched_attributes`` deterministically extracts the REAL
   overlaps between the movie and the request (genres, themes, personality
   traits vs the user's loved movies, parsed-intent fields).
2. The LLM prompt embeds only those verified attributes and explicitly
   forbids referencing anything else; the model's job is wording, not facts.
3. The reply passes a grounding check (no attribute outside the verified
   set, no negated claims like "despite lacking"); on failure we fall back
   to a deterministic template so the sentence can never invent attributes.

The structured ``MatchedAttributes`` and the sentence are returned together
in an ``Explanation`` — the graph view needs the list, the card the sentence.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable
from typing import Any, Protocol

from app.schemas.explanation import (
    Explanation,
    LovedMovie,
    MatchedAttribute,
    MatchedAttributes,
    MatchKind,
    UserTasteContext,
)
from app.schemas.intent import QueryIntent

logger = logging.getLogger("app.explain")

# Traits considered high enough to cite when a movie's score crosses them.
NOTABLE_TRAIT_THRESHOLD = 70.0

# Intent → personality trait hints, with the score the movie must reach.
_INTENT_TRAIT_HINTS: dict[str, tuple[str, float]] = {
    "mind-blowing": ("mind_blowing", 70.0),
    "emotional": ("emotion", 70.0),
    "feel-good": ("hopefulness", 65.0),
    "hopeful": ("hopefulness", 65.0),
    "dark": ("darkness", 70.0),
    "funny": ("humor", 70.0),
    "hilarious": ("humor", 70.0),
    "romantic": ("romance", 70.0),
    "twisty": ("plot_complexity", 70.0),
    "complex": ("plot_complexity", 70.0),
    "gripping": ("rewatchability", 65.0),
}

# Reader-facing names for raw trait keys (display only — matching still uses
# the raw keys so loved-movie and intent matches dedupe correctly).
_TRAIT_DISPLAY: dict[str, str] = {
    "mind_blowing": "mind blowing",
    "emotion": "emotional",
    "hopefulness": "hopeful",
    "darkness": "dark",
    "humor": "funny",
    "romance": "romantic",
    "plot_complexity": "twisty",
    "rewatchability": "gripping",
    "violence": "violent",
}

# One canonical intent label per trait — prevents double-citing the same
# underlying signal (e.g. "emotional tone" + "emotional core"). Traits not
# listed here fall back to the generic "<display name> tone" label.
_INTENT_LABELS: dict[str, str] = {
    "emotion": "emotional core",
}


class ExplainableMovie(Protocol):
    """Structural type: the subset of Movie fields explanations use."""

    @property
    def id(self) -> Any: ...
    @property
    def title(self) -> str | None: ...
    @property
    def genres(self) -> list[Any] | None: ...
    @property
    def keywords(self) -> list[Any] | None: ...
    @property
    def personality(self) -> Any: ...


class LLMExplanationCaller(Protocol):
    """Async callable the service uses for the LLM step (swappable in tests)."""

    def __call__(
        self, prompt: str, *, system_prompt: str
    ) -> Awaitable[str]: ...


def _as_lower_list(values: Any) -> list[str]:
    if not values:
        return []
    return [str(value).strip().lower() for value in values if str(value).strip()]


def _label_case(label: str) -> str:
    return label.strip().lower()


# ---------------------------------------------------------------------------
# 1) Deterministic attribute matching — the grounding source of truth.
# ---------------------------------------------------------------------------


def compute_matched_attributes(
    movie: ExplainableMovie,
    query_intent: QueryIntent | None,
    user_taste_profile: UserTasteContext | None,
) -> MatchedAttributes:
    """Extract only the overlaps that genuinely exist in the data."""
    matched = MatchedAttributes()

    movie_genres = _as_lower_list(movie.genres)
    movie_keywords = _as_lower_list(movie.keywords)

    # --- Shared genres: explicit request -----------------------------------
    if query_intent is not None:
        for genre in query_intent.genres_include:
            if _label_case(genre) in movie_genres:
                matched.genres.append(genre)

    # --- Shared themes: requested themes + loved-movie keywords -------------
    wanted_themes = list(query_intent.themes) if query_intent else []
    loved_keywords = (
        user_taste_profile.loved_keywords if user_taste_profile else []
    )
    for theme in (*wanted_themes, *loved_keywords):
        normalized = _label_case(theme)
        if any(normalized in keyword for keyword in movie_keywords) and normalized not in [
            _label_case(t) for t in matched.themes
        ]:
            matched.themes.append(theme)

    # --- Loved-movie overlaps: genres + keywords per loved movie ------------
    if user_taste_profile:
        for loved in user_taste_profile.loved_movies:
            shared_genres = [
                genre
                for genre in loved.genres
                if _label_case(genre) in movie_genres
            ]
            shared_keywords = [
                keyword
                for keyword in loved.keywords
                if _label_case(keyword) in movie_keywords
            ]
            if shared_genres or shared_keywords:
                detail_bits: list[str] = []
                if shared_genres:
                    detail_bits.append(f"shared genres: {', '.join(shared_genres)}")
                if shared_keywords:
                    detail_bits.append(f"shared themes: {', '.join(shared_keywords)}")
                matched.loved_movie_overlaps.append(
                    MatchedAttribute(
                        kind=MatchKind.rating,
                        label=f"{loved.title} ({loved.score:g}/10)",
                        detail="; ".join(detail_bits) or "matches your favorites",
                    )
                )

    # --- Personality: trait overlap vs loved movies + intent hints ----------
    movie_personality = movie.personality if isinstance(movie.personality, dict) else {}
    loved_personalities = [
        loved.personality
        for loved in (user_taste_profile.loved_movies if user_taste_profile else [])
        if isinstance(loved.personality, dict)
    ]
    if loved_personalities:
        for trait, value in movie_personality.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and float(value) >= NOTABLE_TRAIT_THRESHOLD
            ):
                # The movie itself must score high on the trait AND the user's
                # loved movies must too — a low-emotion movie is never cited
                # for "emotion" just because the user loves emotional films.
                values = [
                    float(profile.get(trait, 0))
                    for profile in loved_personalities
                    if isinstance(profile.get(trait), (int, float))
                ]
                if values and sum(values) / len(values) >= NOTABLE_TRAIT_THRESHOLD:
                    trait_key = str(trait)
                    if trait_key not in matched.personality_traits:
                        matched.personality_traits.append(trait_key)

    if query_intent is not None:
        text_blob = " ".join(
            [
                query_intent.mood or "",
                query_intent.ending_type or "",
                *query_intent.themes,
            ]
        ).lower()
        for hint, (trait, floor) in _INTENT_TRAIT_HINTS.items():
            if hint in text_blob:
                value = movie_personality.get(trait)
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and value >= floor
                ):
                    # Raw trait key ("mind_blowing") so it matches the keys the
                    # loved-movies loop uses — spaced labels only in intent_matches.
                    if trait not in matched.personality_traits:
                        matched.personality_traits.append(trait)
                    trait_label = _TRAIT_DISPLAY.get(trait, trait.replace("_", " "))
                    intent_label = _INTENT_LABELS.get(trait, f"{trait_label} tone")
                    if intent_label not in matched.intent_matches:
                        matched.intent_matches.append(intent_label)

    return matched


# ---------------------------------------------------------------------------
# 2) Deterministic template explanation (always available fallback).
# ---------------------------------------------------------------------------


def template_explanation(matched: MatchedAttributes, movie_title: str) -> str:
    """Build a grounded 1-3 sentence explanation without any LLM."""
    sentences: list[str] = []

    if matched.genres:
        genres = ", ".join(matched.genres)
        sentences.append(f"{movie_title} is a {genres} film")
    elif matched.loved_movie_overlaps:
        first = matched.loved_movie_overlaps[0]
        sentences.append(f"{movie_title} sits close to {first.label}")

    if matched.themes:
        themes = ", ".join(matched.themes)
        sentences.append(f"It explores {themes}")

    if matched.personality_traits:
        traits = ", ".join(
            _TRAIT_DISPLAY.get(trait, trait.replace("_", " "))
            for trait in matched.personality_traits
        )
        sentences.append(f"It leans into {traits}")

    if matched.intent_matches:
        intents = ", ".join(matched.intent_matches)
        sentences.append(f"It matches your ask for {intents}")

    if matched.loved_movie_overlaps:
        overlaps = "; ".join(
            f"{overlap.label} ({overlap.detail})" if overlap.detail else overlap.label
            for overlap in matched.loved_movie_overlaps
        )
        sentences.append(f"It shares real ground with {overlaps}")

    if not sentences:
        return (
            f"{movie_title} appears in your results, though we could not verify "
            "specific overlaps with your request."
        )

    text = sentences[0]
    rest = [sentence[0].lower() + sentence[1:] for sentence in sentences[1:]]
    if rest:
        text += ", and " + ", and ".join(rest)
    return text + "."


# ---------------------------------------------------------------------------
# 3) LLM wording + grounding check.
# ---------------------------------------------------------------------------


def _attribute_vocabulary(
    matched: MatchedAttributes,
    movie_title: str,
    movie: ExplainableMovie | None = None,
    intent: QueryIntent | None = None,
) -> set[str]:
    """Lowercased tokens/phrases the explanation is allowed to reference.

    Two tiers, both strictly real data:
    - ``matched``: the verified overlaps (what the prompt was given).
    - movie/intent attributes: anything genuinely present in the movie's
      genres/keywords or the parsed intent. Citing a real movie keyword
      that wasn't an overlap is word choice, not hallucination.
    """
    allowed = {movie_title.lower()}
    for genre in matched.genres:
        allowed.add(genre.lower())
    for theme in matched.themes:
        allowed.add(theme.lower())
    for trait in matched.personality_traits:
        allowed.add(trait.lower())
    for item in matched.intent_matches:
        allowed.add(item.lower())
    for overlap in matched.loved_movie_overlaps:
        allowed.add(overlap.label.lower())
        if overlap.detail:
            allowed.add(overlap.detail.lower())
    if movie is not None:
        allowed.update(_as_lower_list(movie.genres))
        allowed.update(_as_lower_list(movie.keywords))
    if intent is not None:
        for value in (
            intent.mood,
            intent.pace,
            intent.ending_type,
            intent.time_period,
            intent.violence_tolerance,
            *intent.themes,
            *intent.themes_exclude,
            *intent.genres_include,
            *intent.genres_exclude,
            *intent.similar_to,
        ):
            if value:
                allowed.add(value.lower())
    return allowed


# Function words, discourse boilerplate, and contraction fragments that can
# never assert a verifiable attribute.
_GENERIC_WORDS: frozenset[str] = frozenset(
    """
    a an the and or but so if then than that this these those there here it
    its is are was were be been being am do does did done doing have has had
    having i you your yours we our us they them their he she him her his will
    of to in on at by for with from into onto over under about across after
    before between during through without within along among around behind
    as because since although though while when where why how what which who
    whom whose whether once both each every either neither any all some no
    nor not never none only just still yet also too very really quite rather
    almost more most much many less least few own same such won can cannot
    didn doesn isn aren wasn weren hasn haven shouldn wouldn couldn ain s t
    ll ve re d m em ok
    film films movie movies cinema story stories plot scene scenes watch
    watching watched see seeing seen must sci fi ai cgi
    deliver delivers delivering offer offers offering bring brings bringing
    explore explores exploring find finds finding hit hits hitting
    match matches matching matched ask asks asked asking want wants wanted
    lean leans leaning tone vibe vibes feel feels feeling felt sense
    recommend recommendation recommended pick picks picked feature features
    fans fan like likes liked love loves loved enjoy enjoys enjoyed result
    results nail nails nails delivers give gives given take takes taken
    share shares shared sharing real truly ground grounds grounded
    favorite favorites insight insights
    """.split()
)

# Pure evaluative adjectives: praise that asserts no verifiable attribute,
# so they never need grounding ("stunning" is opinion; "robotics" is a fact
# claim about the movie and must be backed by data).
_PRAISE_ADJECTIVES: frozenset[str] = frozenset(
    """
    great good excellent amazing stunning gorgeous breathtaking brilliant
    masterful remarkable unforgettable haunting gripping riveting compelling
    powerful beautiful striking bold vivid memorable superb wonderful solid
    strong perfect standout worthy crafted elevated satisfying intense
    """.split()
)


def _is_grounded(
    text: str,
    matched: MatchedAttributes,
    movie_title: str,
    movie: ExplainableMovie | None = None,
    intent: QueryIntent | None = None,
) -> bool:
    """Reject explanations referencing attributes outside the real-data set.

    Token-level check: every content word must come from the vocabulary
    (verified overlaps + real movie/intent attributes) or be known-generic
    discourse. Deliberately conservative — anything unknown falls back to
    the template, guaranteeing no invented attributes are ever shown.
    """
    lowered = text.lower()
    if re.search(r"\b(despite (lacking|not having))\b", lowered):
        return False
    vocabulary = _attribute_vocabulary(matched, movie_title, movie, intent)
    allowed = set(vocabulary)
    for phrase in vocabulary:
        allowed.update(re.findall(r"[a-z0-9]+", phrase))

    text_tokens = re.findall(r"[a-z0-9]+", lowered)
    for token in text_tokens:
        if token in allowed or token in _GENERIC_WORDS or token in _PRAISE_ADJECTIVES:
            continue
        return False

    # Substance requirement: at least one VERIFIED match must actually appear
    # in the text (not just generic filler), so a vacuous reply like "ok"
    # can never masquerade as an explanation.
    substance: set[str] = set()
    for phrase in (
        *matched.genres,
        *matched.themes,
        *matched.personality_traits,
        *matched.intent_matches,
        *[overlap.label for overlap in matched.loved_movie_overlaps],
    ):
        substance.update(re.findall(r"[a-z0-9]+", phrase.lower()))
    return any(token in substance for token in text_tokens)


EXPLANATION_SYSTEM_PROMPT = """You write 1-3 sentence movie explanations.

You will receive the movie title and a VERIFIED list of matching attributes
(shared genres, shared themes, personality traits, intent matches). Rules:
1. Reference ONLY attributes from the verified list. Do not invent themes,
   plot points, tonal qualities, or comparisons not present in the list.
2. If the list mentions specific movies the user loved, you may cite them.
3. Natural, specific, warm tone. No bullet points. 1-3 sentences.
4. Output ONLY the explanation text.
"""


async def _default_llm_caller(prompt: str, *, system_prompt: str) -> str:
    """Route through the shared chat client (JSON mode off: plain text)."""
    from app.services.llm_client import create_chat_client

    client = create_chat_client()
    try:
        body = await client.complete_text(
            system_prompt=system_prompt, user_prompt=prompt
        )
    finally:
        await client.aclose()
    return body


def _llm_prompt(movie_title: str, matched: MatchedAttributes) -> str:
    verified = {
        "shared_genres": matched.genres,
        "shared_themes": matched.themes,
        "personality_traits": matched.personality_traits,
        "intent_matches": matched.intent_matches,
        "loved_movie_overlaps": [
            f"{item.label}: {item.detail}" if item.detail else item.label
            for item in matched.loved_movie_overlaps
        ],
    }
    import json

    return (
        f"Movie: {movie_title}\n"
        f"Verified matching attributes (the ONLY things you may reference):\n"
        f"{json.dumps(verified, indent=2)}\n\n"
        "Write the explanation now."
    )


async def explain_recommendation(
    movie: ExplainableMovie,
    query_intent: QueryIntent | None,
    user_taste_profile: UserTasteContext | None,
    *,
    llm_caller: LLMExplanationCaller | None = None,
) -> Explanation:
    """Generate a grounded explanation: sentence + structured attributes."""
    movie_title = movie.title or "This movie"
    matched = compute_matched_attributes(movie, query_intent, user_taste_profile)

    text: str | None = None
    source = "template"
    if llm_caller is None:
        llm_caller = _default_llm_caller

    if not matched.is_empty():
        try:
            candidate = await llm_caller(
                _llm_prompt(movie_title, matched),
                system_prompt=EXPLANATION_SYSTEM_PROMPT,
            )
            cleaned = candidate.strip().strip('"')
            if cleaned and _is_grounded(cleaned, matched, movie_title, movie, query_intent):
                text = cleaned
                source = "llm"
            else:
                logger.warning(
                    "LLM explanation for %r failed grounding check; using template",
                    movie_title,
                )
        except Exception as exc:  # noqa: BLE001 — explanation must never break search
            logger.warning("LLM explanation failed (%s); using template", exc)

    if text is None:
        text = template_explanation(matched, movie_title)

    return Explanation(
        movie_id=str(getattr(movie, "id", "")),
        movie_title=movie_title,
        text=text,
        matched_attributes=matched,
        source=source,
        query_intent=query_intent,
    )


# ---------------------------------------------------------------------------
# 4) Taste context loading (from real rating history).
# ---------------------------------------------------------------------------

_LOVED_THRESHOLD = 8.0


async def build_user_taste_context(
    session: Any, user_id: Any, loved_limit: int = 5
) -> UserTasteContext | None:
    """Load the user's highest-rated movies for taste grounding.

    Returns None for anonymous users or when no 8+ ratings exist.
    """
    if user_id is None:
        return None
    from sqlalchemy import select

    from app.models import Movie, Rating

    statement = (
        select(Movie, Rating.score)
        .join(Rating, Rating.movie_id == Movie.id)
        .where(Rating.user_id == user_id, Rating.score >= _LOVED_THRESHOLD)
        .order_by(Rating.score.desc())
        .limit(loved_limit)
    )
    rows = (await session.execute(statement)).all()

    loved = [
        LovedMovie(
            title=movie.title or "Unknown",
            score=float(score),
            genres=[str(genre) for genre in (movie.genres or [])],
            keywords=[str(keyword) for keyword in (movie.keywords or [])],
            personality=movie.personality
            if isinstance(movie.personality, dict)
            else None,
        )
        for movie, score in rows
    ]
    if not loved:
        return None
    return UserTasteContext(loved_movies=loved)
