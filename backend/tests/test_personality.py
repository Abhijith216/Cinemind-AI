"""Tests for Module 7 personality vectors (offline: fakes only, no network/DB)."""

import pytest
from pydantic import ValidationError

from app.schemas.common import MoviePersonalityOut
from app.services.llm_client import LLMError
from app.services.personality import (
    PERSONALITY_SYSTEM_PROMPT,
    PersonalityError,
    _parse_args,
    analyze_personality,
    backfill_personality,
    build_personality_dossier,
    main,
)

TRAITS = (
    "emotion",
    "mind_blowing",
    "darkness",
    "humor",
    "violence",
    "romance",
    "hopefulness",
    "plot_complexity",
    "rewatchability",
)


class FakeMovie:
    def __init__(
        self,
        id: int,
        title: str,
        *,
        overview: str = "A film.",
        genres: list[str] | None = None,
        keywords: list[str] | None = None,
        release_year: int | None = 2020,
    ) -> None:
        self.id = id
        self.title = title
        self.overview = overview
        self.genres = genres or ["Drama"]
        self.keywords = keywords or ["identity"]
        self.release_year = release_year
        self.personality: dict[str, int] | None = None


# --- dossier ----------------------------------------------------------------------


def test_dossier_contains_title_genres_keywords_overview() -> None:
    movie = FakeMovie(1, "Arrival", genres=["Sci-Fi"], keywords=["time"])
    dossier = build_personality_dossier(movie)
    assert "Title: Arrival (2020)" in dossier
    assert "Genres: Sci-Fi" in dossier
    assert "Keywords: time" in dossier
    assert "Overview: A film." in dossier


def test_dossier_truncates_long_overview() -> None:
    movie = FakeMovie(1, "Long", overview="word " * 2000)
    dossier = build_personality_dossier(movie)
    assert len(dossier) < 2000
    assert "…" in dossier


# --- prompt contract ---------------------------------------------------------------


def test_prompt_demands_json_only_and_discarded_reasoning() -> None:
    lowered = PERSONALITY_SYSTEM_PROMPT.lower()
    assert "only a json object" in lowered
    assert "reason silently" in lowered
    for trait in TRAITS:
        assert trait in lowered


# --- analyze_personality ------------------------------------------------------------


class StubClient:
    """ChatLLMClient double returning a canned validated reply."""

    def __init__(self, reply: dict[str, int]) -> None:
        self.reply = reply
        self.calls: list[dict[str, object]] = []
        self.closed = False

    async def complete_json(
        self, *, system_prompt: str, user_prompt: str, schema_model: type
    ) -> object:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "schema_model": schema_model,
            }
        )
        return schema_model.model_validate(self.reply)

    async def aclose(self) -> None:
        self.closed = True


def _vector(value: int = 50) -> dict[str, int]:
    return {trait: value for trait in TRAITS}


@pytest.mark.asyncio
async def test_analyze_personality_returns_validated_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = StubClient(_vector(72))
    monkeypatch.setattr(
        "app.services.personality.create_chat_client", lambda: stub
    )

    vector = await analyze_personality(FakeMovie(1, "Arrival"))

    assert vector == _vector(72)
    assert stub.closed  # owned client is closed
    call = stub.calls[0]
    assert call["schema_model"] is MoviePersonalityOut
    assert "Arrival" in str(call["user_prompt"])
    assert "ONLY a JSON object" in str(call["system_prompt"])


@pytest.mark.asyncio
async def test_analyze_personality_wraps_llm_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenClient:
        async def complete_json(self, **_kwargs: object) -> object:
            raise LLMError("endpoint down")

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(
        "app.services.personality.create_chat_client", lambda: BrokenClient()
    )

    with pytest.raises(PersonalityError, match="personality scoring failed"):
        await analyze_personality(FakeMovie(1, "Whatever"))


def test_schema_rejects_out_of_range_and_missing_traits() -> None:
    with pytest.raises(ValidationError):
        MoviePersonalityOut.model_validate({**_vector(150)})
    with pytest.raises(ValidationError):
        incomplete = _vector(50)
        del incomplete["humor"]
        MoviePersonalityOut.model_validate(incomplete)


# --- backfill -------------------------------------------------------------------------


class FakeResult:
    def __init__(self, items: list[FakeMovie]) -> None:
        self._items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[FakeMovie]:
        return self._items


class FakeSession:
    """SQL-aware fake: models ``personality IS NULL`` + NOT IN + LIMIT.

    Backed by one static movie set, so every query re-evaluates the real
    predicate — already-scored movies leave the candidate set, exactly like
    Postgres re-queried after each batch commit.
    """

    def __init__(self, movies: list[FakeMovie]) -> None:
        self._movies = movies
        self.committed = 0

    async def scalars(self, statement: object) -> FakeResult:
        import re

        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]
        excluded: set[int] = set()
        if "NOT IN" in compiled:
            inside = compiled.split("NOT IN (")[1].split(")")[0]
            excluded = {int(n) for n in re.findall(r"\d+", inside)}
        limit_match = re.search(r"LIMIT (\d+)", compiled)
        limit = int(limit_match.group(1)) if limit_match else None

        available = [
            movie
            for movie in self._movies
            if movie.personality is None and movie.id not in excluded
        ]
        if limit is not None:
            available = available[:limit]
        return FakeResult(available)

    async def commit(self) -> None:
        self.committed += 1

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSessionmaker:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


def make_analyzer(
    fail_titles: tuple[str, ...] = (), bad_reply_titles: tuple[str, ...] = ()
):
    calls: list[str] = []

    async def analyze(movie: FakeMovie) -> dict[str, int]:
        calls.append(movie.title)
        if movie.title in fail_titles:
            raise PersonalityError("LLM boom")
        if movie.title in bad_reply_titles:
            invalid = _vector(50)
            invalid["humor"] = 999  # out of range → boundary validation fails
            return invalid
        return _vector(60)

    analyze.calls = calls  # type: ignore[attr-defined]
    return analyze


@pytest.mark.asyncio
async def test_backfill_scores_in_batches_and_commits() -> None:
    batch = [FakeMovie(i, f"Movie {i}") for i in range(3)]
    session = FakeSession(batch)
    analyzer = make_analyzer()

    stats = await backfill_personality(
        batch_size=20,
        analyzer=analyzer,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.scored == 3
    assert stats.failed == 0
    assert stats.remaining == 0
    assert session.committed == 1
    assert all(movie.personality == _vector(60) for movie in batch)
    assert analyzer.calls == ["Movie 0", "Movie 1", "Movie 2"]  # one call per movie


@pytest.mark.asyncio
async def test_backfill_isolates_single_movie_failures() -> None:
    poisoned = FakeMovie(1, "poison")
    good = FakeMovie(2, "good")
    session = FakeSession([poisoned, good])
    analyzer = make_analyzer(fail_titles=("poison",))

    stats = await backfill_personality(
        analyzer=analyzer,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.scored == 1
    assert stats.failed == 1
    assert stats.failed_ids == [1]
    assert good.personality is not None
    assert poisoned.personality is None  # stays NULL → retried next run


@pytest.mark.asyncio
async def test_backfill_rejects_invalid_vectors_at_the_boundary() -> None:
    bad = FakeMovie(1, "bad reply")
    session = FakeSession([bad])
    analyzer = make_analyzer(bad_reply_titles=("bad reply",))

    stats = await backfill_personality(
        analyzer=analyzer,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.scored == 0
    assert stats.failed == 1
    assert bad.personality is None
    assert session.committed == 0  # nothing valid → nothing written


@pytest.mark.asyncio
async def test_backfill_respects_limit_exactly() -> None:
    movies = [FakeMovie(i, f"Movie {i}") for i in range(5)]
    session = FakeSession(movies)
    analyzer = make_analyzer()

    stats = await backfill_personality(
        batch_size=2,
        limit=3,
        analyzer=analyzer,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.scored == 3
    assert len(analyzer.calls) == 3


@pytest.mark.asyncio
async def test_backfill_empty_database_is_a_noop() -> None:
    session = FakeSession([])
    stats = await backfill_personality(
        analyzer=make_analyzer(),  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )
    assert stats.scored == 0 and stats.failed == 0 and stats.remaining == 0


@pytest.mark.asyncio
async def test_backfill_rejects_nonpositive_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        await backfill_personality(batch_size=0, analyzer=make_analyzer())  # type: ignore[arg-type]


# --- CLI ---------------------------------------------------------------------------------


def test_cli_requires_backfill_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "Nothing to do" in capsys.readouterr().err


def test_cli_parses_limit_and_batch_size() -> None:
    args = _parse_args(["--backfill", "--limit", "5", "--batch-size", "10"])
    assert args.backfill and args.limit == 5 and args.batch_size == 10
