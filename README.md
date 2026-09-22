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

### Module 1 — Data ingestion (TMDb → Postgres) *(next)*

`app/services/ingestion/`: TMDb client, upsert service, resumable CLI.
Requires `TMDB_API_KEY` in `backend/.env`.

### Module 2 — Embedding generation *(pending)*

Synopsis + themes + keywords → `text-embedding-3-large` vector stored in
`movies.embedding` (dimension from `EMBEDDING_DIMENSIONS`).

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
