"""Tests for the embeddings service (no network, no Postgres required)."""

import asyncio
import re
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.common import MovieOut, MoviePersonalityOut
from app.services.embeddings import (
    EmbeddingClient,
    EmbeddingError,
    EmbeddingStats,
    build_embedding_text,
    embed_all_missing_movies,
    embed_movie,
)


class _MovieLike:
    """Minimal movie-shaped object for build_embedding_text."""

    def __init__(
        self,
        title: str,
        overview: str | None,
        genres: list[str],
        keywords: list[str],
        release_year: int | None = None,
    ) -> None:
        self.title = title
        self.overview = overview
        self.genres = genres
        self.keywords = keywords
        self.release_year = release_year


# --- build_embedding_text ------------------------------------------------------


def test_text_leads_with_themes_over_prose() -> None:
    movie = _MovieLike(
        title="Interstellar",
        overview="A team of explorers travel through a wormhole in space.",
        genres=["Science Fiction", "Adventure", "Drama"],
        keywords=["space", "time travel", "father-daughter relationship"],
        release_year=2014,
    )
    text = build_embedding_text(movie)

    # Themes (keywords + genres) must appear before the overview prose.
    assert text.index("Themes:") < text.index("Overview:")
    assert "Title: Interstellar (2014)" in text
    assert "space, time travel, father-daughter relationship" in text
    assert "Science Fiction, Adventure, Drama" in text


def test_text_dedupes_theme_words_and_handles_empty_fields() -> None:
    movie = _MovieLike(
        title="X",
        overview=None,
        genres=["Drama", "Drama"],
        keywords=["Drama"],
    )
    text = build_embedding_text(movie)
    # The Themes line (keywords + genres merged) is deduplicated...
    assert "\nThemes: Drama\n" in text
    # ...while the Genres line lists what TMDb sent (no synthetic dedup).
    assert "Genres: Drama, Drama\n" in text
    assert "no synopsis available" in text


def test_text_truncates_very_long_overview() -> None:
    movie = _MovieLike(
        title="Long",
        overview="word " * 500,
        genres=[],
        keywords=[],
    )
    text = build_embedding_text(movie)
    overview_part = text.split("Overview: ")[1]
    assert len(overview_part) < 1100


# --- Pydantic boundary (fixed regression test) ---------------------------------


def test_movie_personality_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValidationError):
        MoviePersonalityOut.model_validate({"emotion": 150})


def test_movie_out_accepts_personality_object() -> None:
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "tmdb_id": 1,
        "title": "T",
        "personality": {
            "emotion": 10,
            "mind_blowing": 20,
            "darkness": 30,
            "humor": 40,
            "violence": 50,
            "romance": 60,
            "hopefulness": 70,
            "plot_complexity": 80,
            "rewatchability": 90,
        },
    }
    parsed = MovieOut.model_validate(payload)
    assert parsed.personality is not None
    assert parsed.personality.rewatchability == 90


# --- EmbeddingClient ------------------------------------------------------------


def _client_with_responses(
    responses: list[httpx.Response], *, dimensions: int = 1536
) -> EmbeddingClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    return EmbeddingClient(
        api_key="test-key",
        model="text-embedding-3-large",
        dimensions=dimensions,
        transport=httpx.MockTransport(handler),
    )


def test_client_sends_model_dimensions_and_preserves_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # Return embeddings out of order; client must restore input order.
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2] * 1536},
                    {"index": 0, "embedding": [0.1] * 1536},
                ]
            },
        )

    client = EmbeddingClient(
        api_key="k",
        model="text-embedding-3-large",
        dimensions=1536,
        transport=httpx.MockTransport(handler),
    )
    vectors = asyncio.run(client.embed_batch(["first", "second"]))
    asyncio.run(client.aclose())

    body = requests[0].read().decode()
    assert '"model":"text-embedding-3-large"' in body
    assert '"dimensions":1536' in body
    assert vectors[0][0] == pytest.approx(0.1)  # index 0 came back second
    assert vectors[1][0] == pytest.approx(0.2)


def test_client_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = _patch_sleeps(monkeypatch)
    client = _client_with_responses(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5] * 1536}]}),
        ]
    )
    vectors = asyncio.run(client.embed_batch(["hello"]))
    asyncio.run(client.aclose())
    assert vectors[0][0] == pytest.approx(0.5)
    assert len(sleeps) == 1


def test_client_raises_on_wrong_dimension_count() -> None:
    client = _client_with_responses(
        [httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 10}]})]
    )
    with pytest.raises(EmbeddingError, match="dims"):
        asyncio.run(client.embed_batch(["hello"]))
    asyncio.run(client.aclose())


def test_client_rejects_empty_api_key() -> None:
    with pytest.raises(EmbeddingError):
        EmbeddingClient(api_key="", model="m", dimensions=1536)


def _patch_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace embeddings' asyncio.sleep with a recording no-op awaitable."""
    sleeps: list[float] = []

    class _Noop:
        def __init__(self, delay: float) -> None:
            self.delay = delay

        def __await__(self):
            sleeps.append(self.delay)

            async def _noop() -> None:
                return None

            return _noop().__await__()

    monkeypatch.setattr(
        "app.services.embeddings.asyncio.sleep", lambda delay: _Noop(delay)
    )
    return sleeps


# --- embed_all_missing_movies with fakes ----------------------------------------


class FakeMovie:
    """ORM-movie stand-in with a settable embedding attribute."""

    def __init__(self, id: Any, title: str) -> None:  # noqa: A002 - mirrors ORM
        self.id = id
        self.title = title
        self.overview = "An overview."
        self.genres = ["Drama"]
        self.keywords = ["space"]
        self.release_year = 2020
        self.embedding = None


class FakeResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return self._items


class FakeSession:
    """SQL-aware fake: honors LIMIT and NOT IN (...) like a real query."""

    def __init__(self, batches: list[list[FakeMovie]]) -> None:
        self._batches = batches
        self.committed = 0

    async def scalars(self, statement: Any) -> FakeResult:
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        excluded: set[int] = set()
        if "NOT IN" in compiled:
            inside = compiled.split("NOT IN (")[1].split(")")[0]
            excluded = {int(n) for n in re.findall(r"\d+", inside)}
        limit_match = re.search(r"LIMIT (\d+)", compiled)
        limit = int(limit_match.group(1)) if limit_match else None

        while self._batches:
            batch = self._batches.pop(0)
            filtered = [m for m in batch if m.id not in excluded]
            if not filtered:
                continue  # everything excluded → like an empty DB result
            if limit is not None:
                filtered = filtered[:limit]
            return FakeResult(filtered)
        return FakeResult([])

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


class FakeEmbeddingClient:
    def __init__(self, fail_texts_containing: str | None = None) -> None:
        self.batches_seen: list[int] = []
        self.vectors = [0.1] * 1536
        self._fail_texts_containing = fail_texts_containing

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batches_seen.append(len(texts))
        if self._fail_texts_containing and any(
            self._fail_texts_containing in text for text in texts
        ):
            raise EmbeddingError("permanent failure")
        return [list(self.vectors) for _ in texts]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_backfill_embeds_in_batches_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.embeddings._require_matching_dimensions", lambda: None
    )
    batch1 = [FakeMovie(i, f"Movie {i}") for i in range(3)]
    session = FakeSession(batches=[batch1, []])  # one full batch, then stop
    fake_client = FakeEmbeddingClient()

    stats = await embed_all_missing_movies(
        batch_size=100,
        client=fake_client,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.embedded == 3
    assert stats.failed == 0
    assert fake_client.batches_seen == [3]
    assert session.committed == 1
    assert all(movie.embedding == [0.1] * 1536 for movie in batch1)


@pytest.mark.asyncio
async def test_backfill_skips_failing_batch_and_stays_resumable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.embeddings._require_matching_dimensions", lambda: None
    )
    poisoned = [FakeMovie(1, "bad movie")]
    good = [FakeMovie(2, "good movie")]
    session = FakeSession(batches=[poisoned, poisoned, good, []])
    fake_client = FakeEmbeddingClient(fail_texts_containing="bad movie")
    stats = await embed_all_missing_movies(
        batch_size=100,
        client=fake_client,  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )

    assert stats.embedded == 1
    assert stats.failed == 1
    assert stats.failed_ids == [1]
    assert good[0].embedding == [0.1] * 1536
    assert poisoned[0].embedding is None  # stays NULL, retried next run


@pytest.mark.asyncio
async def test_backfill_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.embeddings._require_matching_dimensions", lambda: None
    )
    batch = [FakeMovie(i, f"Movie {i}") for i in range(5)]
    session = FakeSession(batches=[batch, [], [], []])
    stats = await embed_all_missing_movies(
        batch_size=100,
        limit=2,
        client=FakeEmbeddingClient(),  # type: ignore[arg-type]
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
    )
    assert stats.embedded == 2


def test_embed_movie_returns_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    movie = _MovieLike(
        title="Arrival",
        overview="A linguist works with the military...",
        genres=["Science Fiction", "Drama"],
        keywords=["first contact", "time"],
        release_year=2016,
    )
    fake_client = FakeEmbeddingClient()

    vector = asyncio.run(embed_movie(movie, client=fake_client))  # type: ignore[arg-type]

    assert len(vector) == 1536
    assert fake_client.batches_seen == [1]


def test_embedding_stats_defaults() -> None:
    stats = EmbeddingStats()
    assert stats.embedded == 0 and stats.failed == 0 and stats.remaining == 0
