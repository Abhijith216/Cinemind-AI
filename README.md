# CineMind

**Explainable AI movie discovery.** Describe what you're in the mood for —
*"something like Interstellar but not about space, emotional, mind-blowing
ending"* — and CineMind returns ranked recommendations, each with a
plain-English explanation grounded in the movie's actual attributes (genres,
keywords, personality traits, ratings) rather than LLM guesswork.

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
backend/                 FastAPI service (modules 1–8 live here as packages)
  cinemind/
    core/                settings (pydantic-settings), DB engine/session
    db/                  SQLAlchemy models + Alembic migrations
    api/                 HTTP routers (all endpoints have Pydantic schemas)
  migrations/            Alembic environment + versions
  tests/                 pytest suite (runs without Postgres)
frontend/                Next.js app (module 9)
docker-compose.yml       Postgres 17 + pgvector
.env.example             copy to .env and fill in
```

## Quickstart

```bash
# 0) One-time setup
cp .env.example .env                 # then fill in TMDB/LLM keys as needed

# 1) Database (requires Docker)
docker compose up -d                 # Postgres 17 + pgvector on :5432

# 2) Backend
python -m venv .venv
.venv/Scripts/pip install -e "backend[local-embeddings]"   # Windows Git Bash
# macOS/Linux: pip install -e "backend[local-embeddings]"
.venv/Scripts/python -m alembic upgrade head --app-dir backend
.venv/Scripts/python -m uvicorn cinemind.main:app --app-dir backend --reload --port 8000

# 3) Frontend
cd frontend && npm install && npm run dev   # http://localhost:3000
```

No Docker yet? Everything below still typechecks and unit-tests without a DB;
endpoints report `"database": "down"` until Postgres is reachable.

## Modules

### ✅ Phase 0 — Scaffold (done)

FastAPI app factory with CORS + lifespan-managed engine; strict-typed
settings; SQLAlchemy 2.0 async models for `movies` (JSONB `raw` + pgvector
`embedding`), `movie_personality` (9 traits × 0–100), `users`, `ratings`,
`taste_profiles`; Alembic migration `0001` that enables `pgvector` and creates
all tables; `/api/health` reporting DB reachability; Next.js 15 + Tailwind v4
frontend with a placeholder discovery page that pings backend health.

**Verify:**

```bash
# Backend (no Postgres needed)
.venv/Scripts/python -m pytest backend/tests -q
.venv/Scripts/python -m mypy backend/cinemind

# With Docker Postgres running:
docker compose up -d
.venv/Scripts/python -m alembic upgrade head --app-dir backend
.venv/Scripts/python -m uvicorn cinemind.main:app --app-dir backend --port 8000 &
curl http://localhost:8000/api/health        # {"status":"ok",...,"database":"up"}

# Frontend
cd frontend && npm run typecheck && npm run build
```

**Module 1 — Data ingestion (TMDb → Postgres):** planned next. Will add
`cinemind/ingestion/` with a TMDb client, upsert service, and a CLI entrypoint
(`python -m cinemind.ingestion --pages 5`), plus README test instructions.

### Module 2 — Embedding generation *(pending)*

Synopsis + themes + keywords → `text-embedding-3-large` vector (1536 dims,
truncated) stored in `movies.embedding`; provider switch via
`CINEMIND_EMBEDDING_PROVIDER=openai|local`.

### Module 3 — Hybrid retrieval *(pending)*

```
score = 0.45*semantic + 0.20*user_history + 0.15*genre
      + 0.10*ratings + 0.10*popularity
```

### Module 4 — LLM query understanding *(pending)*
### Module 5 — Explainable recommendation generator *(pending)*
### Module 6 — User taste profile *(pending)*
### Module 7 — Movie personality vector *(pending)*
### Module 8 — Conversational orchestration *(pending)*
### Module 9 — Frontend (chat UI, movie cards, explanation panel, taste chart) *(pending)*

## Engineering standards

- **Types everywhere:** TypeScript `strict` (+ `noUncheckedIndexedAccess`);
  Python type hints with `mypy --strict` clean.
- **Schemas at the boundary:** every endpoint gets Pydantic request/response
  models (`backend/cinemind/schemas.py` and per-module schemas).
- **No hardcoded secrets:** everything flows through `.env` +
  `pydantic-settings` (`cinemind/core/config.py`, prefix `CINEMIND_`).
- **Explicit over clever:** plain functions, named weights, docstrings.
