# CineMind

**Explainable AI movie discovery.** Describe what you're in the mood for —
*"something like Interstellar but not about space, emotional, mind-blowing
ending"* — and CineMind returns ranked recommendations, each with a
plain-English explanation grounded in real movie attributes, not LLM vibes.

## Stack

| Layer      | Tech |
| ---------- | ---- |
| Frontend   | Next.js (App Router) + TypeScript (strict) + Tailwind CSS + shadcn/ui + Framer Motion |
| Backend    | FastAPI (Python 3.11+), typed + Pydantic everywhere |
| Database   | PostgreSQL + pgvector (embeddings) + JSONB (flexible attributes) |
| Movie data | TMDb API |
| LLM        | OpenAI-compatible chat model (query understanding + explanations) |
| Embeddings | OpenAI `text-embedding-3-large` (or local sentence-transformers to cut cost) |

## Repository layout

```
frontend/               Next.js app (module 9)
backend/
  app/
    api/                route handlers (all responses via Pydantic schemas)
    core/               config (pydantic-settings), DB engine/session
    models/             SQLAlchemy models (movies, personalities, users, ratings, taste)
    schemas/            Pydantic request/response schemas
    services/           ingestion, embeddings, retrieval, llm (built in phases)
    main.py             FastAPI app factory
  alembic/              migrations (0001 creates pgvector extension + all tables)
  requirements.txt      runtime deps
  requirements-dev.txt  test tooling
  Dockerfile            backend image (runs alembic upgrade head on boot)
docker-compose.yml      postgres+pgvector, backend, frontend
```

## Quickstart — one command for the full stack

```bash
cp backend/.env.example backend/.env   # fill in keys when you need TMDb/LLM features
docker compose up --build
```

That starts:
- **Postgres 17 + pgvector** on `localhost:5432` (extension pre-enabled image `pgvector/pgvector`)
- **FastAPI** on `http://localhost:8000` — migrations run automatically on boot
- **Next.js** on `http://localhost:3000`

### Verify the deliverable

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0","database":"up"}

# Postgres really is Postgres, with pgvector:
docker compose exec db psql -U cinemind -d cinemind -c "SELECT extname FROM pg_extension WHERE extname='vector';"

# Stop everything:
docker compose down
```

## Local (no Docker) development

```bash
# Backend
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements-dev.txt   # Windows Git Bash
# macOS/Linux: pip install -r backend/requirements-dev.txt
cd backend && ../.venv/Scripts/python -m alembic upgrade head
../.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Without Postgres reachable, `/health` still returns 200 with
`"database":"down"`, so the API boots anywhere.

## Modules (build order)

### ✅ Phase 0 — Scaffold + infra (done)

FastAPI app factory (CORS, lifespan-managed engine), strict-mypy typed code,
SQLAlchemy 2.0 async models: `movies` (JSONB `raw` + pgvector `embedding`),
`movie_personality` (9 traits × 0–100), `users`, `ratings`, `taste_profiles`;
Alembic wired to the container (`env.py` pulls `DATABASE_URL` from settings);
`GET /health` + `/api/health` alias with graceful DB degradation; Next.js
placeholder landing page.

**Verify without Docker:**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests -q     # 3 passed
../.venv/Scripts/python -m mypy app                          # no issues
../.venv/Scripts/python -m alembic upgrade head --sql        # prints SQL incl. CREATE EXTENSION vector
curl http://localhost:8000/health                            # 200 (after uvicorn start)
cd ../frontend && npm run typecheck && npm run build         # TSC OK, build OK
```

### ✅ Module 1 — Data ingestion (TMDb → Postgres) *(done)*

`app/services/ingestion.py`:
- `TMDbClient` — typed async wrapper over `/discover/movie`,
  `/movie/top_rated`, `/movie/{id}`, `/movie/{id}/keywords`; exponential
  backoff with jitter on 429/5xx (honors `Retry-After`), works with both the
  v3 `api_key` and a v4 read token (Bearer).
- `ingest_movies(pages)` — pulls *pages* pages of popular + top-rated,
  dedupes by TMDb id, fetches full detail + keywords per movie, upserts on
  `tmdb_id` (never duplicates, safe to re-run), commits per movie (Ctrl-C
  keeps progress), and skips any single failing movie without killing the
  run. Returns an `IngestStats` summary.
- CLI: `python -m app.services.ingestion --pages N`

**Seed the database and verify:**

```bash
# with the compose Postgres running:
docker compose up -d db
cd backend
DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m alembic upgrade head   # once

# put your key in backend/.env (TMDB_API_KEY=...) then:
DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m app.services.ingestion --pages 2

# verify (expected ~380-400 rows: 2 pages × 20 movies × 2 lists, deduped):
docker compose exec db psql -U cinemind -d cinemind \
  -c "SELECT count(*) FROM movies;"
docker compose exec db psql -U cinemind -d cinemind \
  -c "SELECT tmdb_id, title, release_year, genres FROM movies ORDER BY popularity DESC NULLS LAST LIMIT 5;"
```

**Test without any network/DB:**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests -q   # 23 passed
```

### ✅ Database schema (designed + migrated)

```
movies               id, tmdb_id (uniq), title, overview, release_year, runtime,
                     genres JSONB[], keywords JSONB[], language, poster_path,
                     vote_average, vote_count, popularity,
                     embedding vector(1536)  ← pgvector,
                     personality JSONB {emotion, mind_blowing, darkness, humor,
                       violence, romance, hopefulness, plot_complexity,
                       rewatchability} — each 0-100, enforced by Pydantic
users                id, email (uniq), hashed_password, created_at
user_taste_profiles  user_id PK/FK, likes JSONB[], dislikes JSONB[],
                     favorite_themes JSONB[], updated_at
ratings              id, user_id FK, movie_id FK, score (CHECK 1-10), rated_at,
                     UNIQUE (user_id, movie_id)
taste_snapshots      id, user_id FK, month ('2026-09'), dominant_genres JSONB[],
                     dominant_themes JSONB[], created_at, UNIQUE (user_id, month)
```

Indexes: `tmdb_id` unique btree · **GIN** on `movies.genres`,
`movies.keywords` · **HNSW cosine** on `movies.embedding`
(`vector_cosine_ops` — HNSW chosen over ivfflat; needs no reindex training
and pgvector ≥ 0.5 on the `pgvector/pgvector:pg17` image supports it) ·
unique `(user_id, movie_id)` on ratings · unique `(user_id, month)` on
snapshots.

**Verify against the Docker Postgres:**

```bash
docker compose up -d db
cd backend && DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m alembic upgrade head
cd ..
docker compose exec db psql -U cinemind -d cinemind -c '\d movies'
docker compose exec db psql -U cinemind -d cinemind -c '\di'
```

`\d movies` should list the vector column (`vector(1536)`) and the three
indexes; `\di` shows the GIN/HNSW/unique indexes across all tables.

### ✅ Module 2 — Embedding generation *(done)*

`app/services/embeddings.py`:
- `build_embedding_text(movie)` — keyword-first text blob: `Title / Genres /
  Themes (keywords+genres, deduped) / Overview (truncated)`. Themes lead the
  blob so semantic search keys on them, per the product spec.
- `EmbeddingClient` — OpenAI-compatible `POST /embeddings` with 429/5xx
  exponential backoff (honors `Retry-After`), input-order restoration, and
  dimension validation (`text-embedding-3-large` truncated to 1536 via the
  `dimensions` parameter to match `movies.embedding vector(1536)`).
- `embed_movie(movie)` / `embed_all_missing_movies()` — batch job that finds
  `embedding IS NULL` movies, embeds in batches of 100, writes vectors back
  through pgvector's SQLAlchemy type, and **commits per batch** so a crash
  mid-run is resumable by simply re-running. Permanently failed batches are
  excluded for the rest of the run and reported; they stay NULL and retry
  next run.
- CLI: `python -m app.services.embeddings --backfill`
  (`--batch-size`, `--limit N` for smoke tests)

**Run the backfill + verify:**

```bash
cd backend
# OPENAI_API_KEY (or compatible provider + OPENAI_BASE_URL) in backend/.env:
DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m app.services.embeddings --backfill

# Deliverable check — should match total movie count:
docker compose exec db psql -U cinemind -d cinemind \
  -c "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS embedded, count(*) AS total FROM movies;"

# Sanity check: Interstellar vs Arrival should score far higher than a
# tonally unrelated movie (adjust titles to what you ingested):
docker compose exec db psql -U cinemind -d cinemind -c "
SELECT 1 - (a.embedding <=> b.embedding) AS interstellar_vs_arrival,
       1 - (a.embedding <=> c.embedding) AS interstellar_vs_hangover
FROM movies a, movies b, movies c
WHERE a.title = 'Interstellar'
  AND b.title  = 'Arrival'
  AND c.title  = 'The Hangover';"
```

Expected: `interstellar_vs_arrival` well above `interstellar_vs_hangover`
(text-embedding similarities typically land around 0.4-0.6 for kindred sci-fi
vs ~0.1-0.25 for unrelated pairs — what matters is the gap).

### ✅ Module 3 — Hybrid retrieval *(done)*

`app/services/retrieval.py` + `POST /api/search/hybrid` (`app/api/search.py`).

Two-stage pipeline:
1. **SQL candidates** — `1 - (embedding <=> :query)` computed by pgvector
   (HNSW-indexed), hard filters applied, top **200** candidates.
2. **Python re-rank** — the full formula over the candidate set:

```
final_score = 0.45*semantic_similarity   # 1 - cosine_distance (from SQL)
            + 0.20*user_history_match    # cosine(movie.personality, avg personality of your 8+ ratings)
            + 0.15*genre_similarity      # Jaccard(query genres, movie genres)
            + 0.10*normalized_rating     # min-max within the candidate set
            + 0.10*normalized_popularity # min-max within the candidate set
```

Every component is returned per movie so you can debug the weighting.

**Try it (needs Postgres + OPENAI_API_KEY; embeddings must be backfilled):**

```bash
curl -s -X POST http://localhost:8000/api/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "emotional mind-blowing sci-fi movie",
    "filters": {"genres": ["Science Fiction"], "min_rating": 7},
    "limit": 3
  }' | python -m json.tool
```

Sample response shape (from a seeded DB):

```json
{
  "query": "emotional mind-blowing sci-fi movie",
  "results": [
    {
      "movie": {
        "id": "6f0e…",
        "tmdb_id": 157336,
        "title": "Interstellar",
        "release_year": 2014,
        "genres": ["Adventure", "Drama", "Science Fiction"],
        "personality": {"emotion": 88, "mind_blowing": 95, "darkness": 40,
          "humor": 25, "violence": 30, "romance": 55, "hopefulness": 70,
          "plot_complexity": 90, "rewatchability": 80}
      },
      "final_score": 0.713,
      "components": {
        "semantic_similarity": 0.612,
        "user_history_match": 0.0,
        "genre_similarity": 0.333,
        "normalized_rating": 0.941,
        "normalized_popularity": 0.780
      }
    }
  ],
  "applied_weights": {
    "semantic": 0.45, "history": 0.2, "genre": 0.15,
    "rating": 0.1, "popularity": 0.1
  }
}
```

`filters` support `genres` (any-of), `languages`, `min_rating`,
`min/max_release_year`; `user_id` (UUID) turns on the history component.

**Tests (offline, no DB):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests -q   # 54 passed
```

### ✅ Module 4 — LLM query understanding *(done)*

`app/services/query_understanding.py` + shared `app/services/llm_client.py`.

- `parse_query(user_text, conversation_history)` → `QueryIntent`
  (`app/schemas/intent.py`): `{mood, pace, ending_type, themes,
  themes_exclude, genres_include, genres_exclude, violence_tolerance,
  similar_to, time_period, runtime_max, clarifying_question}`.
  Documented extension: `themes_exclude`, because "like Interstellar but
  **not about space**" is a theme exclusion the agreed fields can't express.
- Strictly **JSON mode** (`response_format: json_object`, temperature 0) +
  Pydantic validation + ONE self-repair round-trip feeding the validation
  error back to the model. No regex parsing of model output, ever.
- Ambiguous requests ("surprise me") raise `AmbiguousQueryError` carrying
  `.question` (shown to the user) and `.intent` (partial fields) — the chat
  layer asks a follow-up instead of getting a forced guess.
- Retries 429/5xx/connection errors with exponential backoff honoring
  `Retry-After`; permanent 4xx fails fast.

**Run it (no API key needed — demo includes a local OpenAI-compatible mock):**

```bash
cd backend && ../.venv/Scripts/python scripts/demo_query_understanding.py
```

Live output for the product-spec query (real pipeline, mock model):

```json
{
  "mood": "emotional",
  "pace": "moderate",
  "ending_type": "mind-blowing twist",
  "themes": ["father-daughter relationship", "time"],
  "themes_exclude": ["space"],
  "genres_include": ["Science Fiction", "Drama"],
  "genres_exclude": [],
  "violence_tolerance": null,
  "similar_to": ["Interstellar"],
  "time_period": null,
  "runtime_max": null,
  "clarifying_question": null
}
```

With a real key, the same call hits your configured `OPENAI_BASE_URL` —
no code changes.

**Tests (13, incl. the five required scenarios):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_query_understanding.py -v
```

### ✅ Module 5 — Explainable recommendations *(done)*

`app/services/explain.py` + `app/schemas/explanation.py`.

- **Anti-hallucination pipeline, three layers:** (1)
  `compute_matched_attributes` deterministically extracts the REAL overlaps
  (query genres ∩ movie genres, requested themes + loved-movie keywords ∩
  movie keywords, loved-movie genre/keyword overlaps with the 8+ ratings
  that produced them, personality traits where *both* the movie and the
  user's loved movies score ≥ 70, intent hints mapped to real trait
  scores); (2) the LLM prompt embeds ONLY those verified attributes and
  forbids anything else; (3) the reply passes a token-level grounding
  check — every content word must come from real data or a known-generic
  whitelist, and at least one verified match must actually be cited —
  otherwise the service falls back to a deterministic template.
- `explain_recommendation(movie, intent, taste)` returns an `Explanation`
  with BOTH representations the frontend needs: `text` (1-3 sentences for
  the card view) and `matched_attributes` (structured list for the graph
  view). `source` reports `"llm"` or `"template"` honestly.
- `build_user_taste_context(session, user_id)` loads the 8+ rated movies
  from the DB for taste grounding; `None` for anonymous users.
- Known trade-off: the grounding check is deliberately conservative — it
  may reject benign LLM phrasing and use the (always truthful) template.

**Deliverable case** (user rated Interstellar 10/10 + Blade Runner 2049
9/10; shown Arrival):

```bash
cd backend && ../.venv/Scripts/python scripts/demo_explain.py
```

Real pipeline output (`source=llm`, mock model provides wording only):

```
Arrival is a Science Fiction, Drama film that explores time, sharing
real ground with Interstellar (10/10) and Blade Runner 2049 (9/10). It
delivers the emotional, mind blowing tone you asked for.
```

The demo also feeds a **lying LLM** ("hilarious robot comedy with car
chases") and shows the fallback: `source=template`, zero invented
attributes. The final spot-check diffs every token in the accepted
sentence against Arrival's real TMDb genres/keywords/trait scores — it
reports `OK: ... zero invented attributes`.

**Tests (16, all offline):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_explain.py -v
```

### Modules 6–9 *(pending)*

User taste profile · movie personality vector · conversational
orchestration · chat UI, movie cards, explanation panel, taste evolution
chart.

## Engineering standards

- **Types everywhere:** TypeScript `strict` (+ `noUncheckedIndexedAccess`);
  Python type hints, `mypy --strict` clean.
- **Schemas at the boundary:** every endpoint gets Pydantic request/response
  models (`backend/app/schemas/`).
- **No hardcoded secrets:** all config via env vars + `pydantic-settings`
  (`DATABASE_URL`, `OPENAI_API_KEY`, `TMDB_API_KEY`, `JWT_SECRET`, ... — see
  `backend/.env.example`).
- **Explicit over clever:** plain functions, named weights, docstrings.
