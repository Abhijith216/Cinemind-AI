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

### Module 3 — Hybrid retrieval *(pending)*

```
score = 0.45*semantic + 0.20*user_history + 0.15*genre
      + 0.10*ratings + 0.10*popularity
```

### Modules 4–9 *(pending)*

LLM query understanding · explainable recommendations · user taste profile ·
movie personality vector · conversational orchestration · chat UI, movie
cards, explanation panel, taste evolution chart.

## Engineering standards

- **Types everywhere:** TypeScript `strict` (+ `noUncheckedIndexedAccess`);
  Python type hints, `mypy --strict` clean.
- **Schemas at the boundary:** every endpoint gets Pydantic request/response
  models (`backend/app/schemas/`).
- **No hardcoded secrets:** all config via env vars + `pydantic-settings`
  (`DATABASE_URL`, `OPENAI_API_KEY`, `TMDB_API_KEY`, `JWT_SECRET`, ... — see
  `backend/.env.example`).
- **Explicit over clever:** plain functions, named weights, docstrings.
