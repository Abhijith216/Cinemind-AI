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

### ✅ Module 6 — User taste profile *(done)*

`app/services/taste_profile.py` + `app/schemas/taste.py` +
`app/api/ratings.py`.

- `update_taste_profile(session, user_id, movie, score)` runs after every
  rating: `score >= 7` merges the movie's genres/keywords into `likes` and
  its keywords into `favorite_themes`; `score <= 4` merges into `dislikes`;
  5–6 stores the rating but leaves the profile alone.
- **Bounded recency = the "light decay":** lists dedupe case-insensitively,
  newly-touched tags move to the front, capped at `MAX_PROFILE_ITEMS = 50`
  — no unbounded growth, recent taste always wins.
- `get_taste_profile(session, user_id)` → `TasteProfileOut` (or `None` for
  users who never rated).
- `POST /api/ratings` (201 create / 200 upsert on re-rate) writes the
  rating **and** updates the profile in the same request; profile update
  shares the transaction. `GET /api/taste-profile/{user_id}` returns the
  current profile (404 until the first rating).
- `snapshot_monthly(session, user_id, month=None)` — the snapshot job you
  call manually (cron later): ranks the month's dominant genres/themes by
  **Σ score** per tag (a 10 counts five times a 2; count-then-name
  tiebreak so the chart is stable) and upserts the `taste_snapshots` row.
  Rebuild any past month by passing `"2025-12"`; returns `None` for months
  with no ratings (the chart skips silent months). December rolls over
  correctly.

**Endpoints:**

```bash
POST /api/ratings            {"user_id": ..., "movie_id": ..., "score": 1-10}
GET  /api/taste-profile/{user_id}
```

**Snapshot job (manual for now):**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m app.services.taste_profile --user-id <uuid> [--month 2026-09]
```

**Tests (25, all offline — service + endpoint via dependency override):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_taste_profile.py -v
../.venv/Scripts/python scripts/demo_taste_profile.py   # POST + GET shown live
```

On a real DB the demo's fake session swaps for `get_db_session` — the
routes are identical.

### ✅ Module 7 — Movie personality vectors *(done)*

`app/services/personality.py`.

- `analyze_personality(movie)` → `{trait: 0-100 int}` for the nine traits.
  ONE LLM call per movie (JSON mode via the shared `ChatLLMClient`, with
  the one-shot self-repair on schema failure); the prompt instructs the
  model to **reason silently and reply with only the JSON object** — no
  reasoning ever reaches the response. The reply is validated by
  `MoviePersonalityOut` (int 0-100 per trait), and the backfill
  re-validates at the DB boundary.
- `backfill_personality()` — same resumable design as the embeddings
  backfill: `personality IS NULL` candidates in stable id order, commit
  per batch, single-movie failures isolated (the rest of the batch still
  scores), failed movies stay NULL and are retried next run, `--limit`
  honored exactly.
- CLI: `python -m app.services.personality --backfill [--batch-size N]
  [--limit N]`.

**Run it (needs OPENAI_API_KEY + DB):**

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://cinemind:cinemind@localhost:5432/cinemind \
  ../.venv/Scripts/python -m app.services.personality --backfill
```

**Demo without keys (20-movie batch, mock model, sanity checks):**

```bash
cd backend && ../.venv/Scripts/python scripts/demo_personality.py
```

Output: 20/20 scored, three sample vectors (comedy → humor 88 / darkness
18 / violence 12; mind-bending sci-fi → mind_blowing 85 / plot_complexity
78; grim thriller → darkness 82 / humor 8) and PASS on all sanity checks.

**Tests (14, offline):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_personality.py -v
```

### ✅ Module 8 — Conversational orchestration *(done)*

`app/services/chat_orchestrator.py` + `app/api/chat.py` +
`app/schemas/chat.py`; persistence in `chat_sessions`/`chat_messages`
(migration `0002_chat_tables.py`).

- `POST /api/chat/message` `{message, session_id?, user_id?, result_limit?}`:
  loads the session history → `parse_query` **with that history** → if the
  model asks a clarifying question it IS the reply (no search) → otherwise
  renders the resolved intent, embeds it, runs hybrid search, generates
  grounded explanations, and returns ranked + explained results with a
  short summary reply. Every turn (user + assistant) is persisted; the
  assistant turn stores the resolved intent payload and the ordered result
  movie ids.
- Multi-turn refinement works because the **intent is re-rendered and
  re-embedded each turn**: "think" after "surprise me" produces a
  mind-bending query even though those words never appeared in turn 1.
  Decade intents ("1990s") and "recent" map onto SQL year filters.
- Unknown `session_id` → 404. Anonymous users are allowed (no taste
  grounding).

**Demo — the product-spec flow, full transcript:**

```bash
cd backend && ../.venv/Scripts/python scripts/demo_chat.py
```

Turns: "surprise me" → clarifying question · "think" → second question ·
"about two hours" → 4 ranked picks with per-movie explanations and matched
attributes · persistence of 1 session + 8 messages.

**Tests (10, offline — includes the required flow as an explicit case):**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_chat_orchestrator.py -v
```

Apply the migration before running against Postgres:

```bash
cd backend && ../.venv/Scripts/python -m alembic upgrade head   # adds 0002 chat tables
```

### ✅ Module 9c — Taste-evolution chart + recommendation graph

The two visual "why/taste" views, working against the demo backend's seeded
user (4 backdated ratings + 4 monthly snapshots):

- **`/taste-evolution`** (`src/app/taste-evolution/page.tsx` +
  `components/taste-evolution-chart.tsx`) — recharts timeline of the
  monthly `taste_snapshots`: one line per dominant genre (amber family) and
  theme (violet family, dashed). A point's value is the tag's **rank** in
  that month, inverted onto a 0–100 scale (Y axis shows #1…#5), so the
  chart literally reads "Mostly Action → Thriller → Science Fiction".
  The user id comes from `?user=` (remembered in localStorage) or a paste
  box; an amber arc summary line states the first→latest dominant genre.
- **`/movie/[id]?user=`** (`components/recommendation-graph-view.tsx`) —
  the recommendation "why" as a **node graph, not a table**: your
  highest-rated movies on the left, the recommended movie on the right,
  and bezier edges labeled with the **concrete** genres/keywords they
  actually share (from `GET /movies/{id}/recommendation-graph`) —
  Interstellar ★10 —— "Science Fiction, Drama · time" ——> Arrival.
  Custom SVG (no graph lib), seed nodes link to their own pages.
- Demo backend seeds the test user `00000000-0000-4000-8000-c1e0deadbeef`
  and prints ready-made URLs for both views on startup
  (`/api/demo/urls` has them as JSON).

```bash
cd backend && ../.venv/Scripts/python scripts/demo_chat_backend.py
# open the two URLs it prints (taste_evolution, graph)
```

### ✅ Module 9b — Chat UI + MovieCard with inline explanations

The first real feature views on the Module 9 shell:

- **`MovieCard`** (`src/components/movie-card.tsx`) — poster (TMDb CDN
  `w500` or a themed fallback), title, year, ★-rating badge, and the
  **explanation sentence shown directly on the card** (the Phase 5/7
  differentiator). A "Why this?" expand reveals the structured matches as
  color-coded chips: Genres / Themes / Personality / Intent / Your
  favorites. `MovieCardRow` renders them as a horizontal scroll strip.
- **`/chat`** (`src/app/chat/page.tsx`) — full transcript (amber user /
  card-surface assistant bubbles), typing indicator, and **quick-reply
  chips** for clarifying turns (derived from the reply text / echoed intent
  themes when the backend has no explicit suggestions). The session id is
  kept in `sessionStorage`, so a reload continues the same conversation;
  recommendations from a search turn render as a `MovieCardRow` under the
  assistant message. (The backend returns complete turns per POST, so the
  UI shows an honest typing indicator rather than fake token streaming.)
- **E2E run without real services:** `backend/scripts/demo_chat_backend.py`
  serves the real FastAPI pipeline on `:8000` (mock OpenAI-compatible LLM +
  embeddings server, SQL-dispatching fake Postgres session — same seams as
  `scripts/demo_chat.py`). CORS already defaults to `localhost:3000`.

```bash
# terminal 1
cd backend && ../.venv/Scripts/python scripts/demo_chat_backend.py
# terminal 2
cd frontend && npm run dev            # http://localhost:3000/chat
# then type: surprise me -> mind-bending thriller -> about two hours
# -> 4 ranked cards, each with its grounded explanation + "Why this?" chips
```

### ✅ Module 9 — Frontend shell

`frontend/` — Next.js 15 App Router + TypeScript strict + Tailwind v4.

- **Routes:** `/` (Discover), `/chat`, `/movie/[id]`, `/profile`,
  `/taste-evolution` — themed placeholder pages behind a working global nav
  (Discover / Chat / My Taste) with active-state highlight.
- **Cinematic theme:** deep-charcoal "darkened theater" palette, projector-beam
  amber primary, violet neon accent, golden `beam` light + film-grain overlay
  (`globals.css`), shadcn/ui-style primitives in `src/components/ui`
  (button/card/badge/input, `components.json` ready for the CLI).
- **Typed API client** (`src/lib/api.ts`): one interface per backend Pydantic
  response model (Phase 10 surface — auth, movies, graph, search, chat,
  ratings, taste), `ApiError` with status + detail, bearer-token helper for
  register/login, base URL from `NEXT_PUBLIC_API_BASE_URL`.

**Verify:**

```bash
cd frontend && npm run dev        # http://localhost:3100
cd frontend && npm run typecheck && npm run build
```

The explanation panel, movie detail page, and the taste evolution chart are
the next frontend increments — the client methods for all of them already
exist.

### ✅ API surface (Phase 10) — documented FastAPI routers

All public routes live under `/api` (health stays at `/` + `/api/health`)
with a named Pydantic response model on every route. FastAPI auto-generates
the docs:

- **Swagger UI:** `http://localhost:8000/docs` · **ReDoc:** `/redoc` ·
  raw schema: `/openapi.json`

| Method | Route | Response model |
|---|---|---|
| POST | `/api/auth/register` | `TokenResponse` (201; 409 duplicate) |
| POST | `/api/auth/login` | `TokenResponse` (401 on bad credentials) |
| GET | `/api/movies/{movie_id}` | `MovieOut` |
| GET | `/api/movies/{movie_id}/recommendation-graph?user_id=` | `RecommendationGraph` |
| POST | `/api/search/hybrid` | `SearchResponse` |
| POST | `/api/chat/message` | `ChatTurnResponse` |
| GET | `/api/chat/sessions/{session_id}` | `ChatSessionOut` |
| POST | `/api/ratings` | `RatingOut` (201 create / 200 re-rate) |
| GET | `/api/users/{user_id}/taste-profile` | `TasteProfileOut` |
| GET | `/api/users/{user_id}/taste-evolution` | `list[TasteSnapshotOut]` |
| GET | `/health`, `/api/health` | `HealthOut` |

Auth: register/login issue HS256 JWTs (`JWT_SECRET`, 7-day expiry) with
stdlib PBKDF2-SHA256 password hashing (`pbkdf2_sha256$<iter>$<salt>$<hash>`).
`JWT_SECRET` must be changed in any real deploy (`backend/.env.example`).
The recommendation graph returns the structured "why": the movie node, the
user's top-rated movies, and per-movie edges with concrete shared
genres/keywords — the same real-overlap discipline as explanations.
New deps: `pyjwt`, `email-validator` (already in requirements).

The taste profile moved to the canonical `/api/users/{user_id}/taste-profile`
path (old `/api/taste-profile/{user_id}` removed).

**Verify:**

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/test_api_surface.py -v
../.venv/Scripts/python -c "from app.main import app; print(len(app.openapi()['paths']), 'paths documented')"
# with the server running: open http://localhost:8000/docs
```

## Engineering standards

- **Types everywhere:** TypeScript `strict` (+ `noUncheckedIndexedAccess`);
  Python type hints, `mypy --strict` clean.
- **Schemas at the boundary:** every endpoint gets Pydantic request/response
  models (`backend/app/schemas/`).
- **No hardcoded secrets:** all config via env vars + `pydantic-settings`
  (`DATABASE_URL`, `OPENAI_API_KEY`, `TMDB_API_KEY`, `JWT_SECRET`, ... — see
  `backend/.env.example`).
- **Explicit over clever:** plain functions, named weights, docstrings.
