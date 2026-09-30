# Deploying CineMind

Target: **Render** (two Docker services) + **Neon** (managed Postgres with
pgvector). Everything below is start-to-finish: by the end you'll have the
live app, a populated movie catalog, and embeddings + personalities built.

> Cheaper alternative: a single $5 VPS running `docker compose -f
> docker-compose.yml up -d --build` gets you the whole stack behind one box —
> see the README's local section. The Render path below is the
> minimum-ops route.

---

## 0. What you need before starting

| Account | Used for | Cost |
| --- | --- | --- |
| [Render](https://render.com) | Backend + frontend hosting | Free tier OK |
| [Neon](https://neon.tech) | Postgres 17 + pgvector | Free tier OK |
| [TMDb](https://www.themoviedb.org/settings/api) | Movie catalog data | Free |
| OpenAI (or any OpenAI-compatible provider) | LLM + embeddings | Pay-per-use |

---

## 1. Architecture

```
Render                          Neon (external)
┌───────────────────┐   TLS     ┌──────────────────────┐
│ cinemind-api      │──────────▶│ Postgres 17          │
│  FastAPI/uvicorn  │  pooled   │  + pgvector          │
│  Docker, port 8000│  + direct │  ep-*.neon.tech      │
└───────────────────┘           └──────────────────────┘
┌───────────────────┐
│ cinemind-web      │   browser fetches https://cinemind-api.onrender.com
│  Next.js standalone│
│  Docker, port 3000│
└───────────────────┘
```

- The blueprint in [render.yaml](render.yaml) defines both services.
- Migrations run automatically on every backend boot (the container
  entrypoint runs `alembic upgrade head` before starting uvicorn).
- The backend health check (`/health`) drives Render's monitoring and
  restarts the service if it stops answering.

---

## 2. Create the Neon database (once)

1. Sign up at neon.tech → **New project** → name it `cinemind`.
2. Neon enables **pgvector** out of the box — nothing to install. (Our
   Alembic migration also runs `CREATE EXTENSION IF NOT EXISTS vector`.)
3. Open **Dashboard → Connection Details** and copy **both** strings:
   - **Pooled** (has `-pooler` in the host, routes through PgBouncer)
     → this is `DATABASE_URL`.
   - **Unpooled / Direct** (no `-pooler`)
     → this is `DATABASE_URL_DIRECT` (migrations + data CLIs need this).
4. Note the branch's connection strings use `postgresql://user:pass@host/db`
   — the backend normalizes them to the asyncpg driver automatically; no
   manual editing needed.

---

## 3. Deploy via Blueprint (once)

1. Push this repo to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo → **Apply**.
   Render reads `render.yaml`, builds both Docker images, and prompts you
   for the `sync: false` env vars. Fill in:
   - `DATABASE_URL` — Neon **pooled** URL
   - `DATABASE_URL_DIRECT` — Neon **direct** URL
   - `TMDB_API_KEY` — your TMDb key
   - `OPENAI_API_KEY` — your OpenAI key
   - `CORS_ORIGINS` — leave `https://cinemind-web.onrender.com` for now
     (fix up in step 4 once you know your real frontend URL)
   - `NEXT_PUBLIC_API_BASE_URL` — leave blank for now (step 4)
3. First deploy takes ~5 min (Docker builds). The backend container runs
   `alembic upgrade head` on boot — the schema (with pgvector) is created
   before the API accepts traffic.

---

## 4. Wire the two URLs together (once, after first deploy)

1. Render dashboard → `cinemind-web` → **Settings** → copy its URL
   (e.g. `https://cinemind-web.onrender.com`).
2. `cinemind-api` → **Environment** → set `CORS_ORIGINS` to that URL → save
   (this redeploys the backend).
3. `cinemind-api` → copy its URL (e.g. `https://cinemind-api.onrender.com`).
4. `cinemind-web` → **Environment** → set `NEXT_PUBLIC_API_BASE_URL` to the
   backend URL → save. This re-builds the frontend with the URL baked in.

---

## 5. Verify the deploy

```bash
# Backend alive + DB reachable (should print "database":"up")
curl https://cinemind-api.onrender.com/health

# Docs render
open https://cinemind-api.onrender.com/docs

# Frontend loads (hero page should show the backend health pill green)
open https://cinemind-web.onrender.com
```

Render's **Logs** tab shows one JSON line per request
(`{"level":"INFO","path":"/api/chat/message",...}`) — filter by `level`,
`path`, or `status` there. Free-tier services spin down after 15 idle
minutes; the first request afterwards takes ~30s (Render shows this in the
dashboard; set a $7/mo Starter plan to avoid it).

---

## 6. One-time production data setup

These run **once** against the live Neon DB. They need your secrets, so run
them from your machine with the **direct** connection (not the pooled one).

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Point the CLIs at Neon (DIRECT url — pooled breaks long-running jobs)
export DATABASE_URL_DIRECT="postgresql://user:pass@ep-x-pooler.../neondb"  # ← replace
export DATABASE_URL="$DATABASE_URL_DIRECT"      # CLIs use migrations_url
export DB_SSL=require
export TMDB_API_KEY=...                          # ← replace
export OPENAI_API_KEY=...                        # ← replace
```

### 6a. Ingest the movie catalog (TMDb)

```bash
python -m app.services.ingestion --pages 20
# ~15-20 min for 20 pages (~400 movies). Safe to Ctrl-C and re-run:
# upserts by tmdb_id, so nothing duplicates.
```

### 6b. Generate embeddings

```bash
python -m app.services.embeddings --backfill
# Batches of 100, resumable — re-run until "remaining: 0".
# Cost: ~$0.01-0.02 per 1000 movies with text-embedding-3-large.
```

### 6c. Generate personality vectors

```bash
python -m app.services.personality --backfill
# One LLM call per movie. Re-runnable; only NULL rows are processed.
```

### 6d. Confirm

```bash
# In the Neon SQL editor (or psql with DATABASE_URL_DIRECT):
SELECT count(*) AS total FROM movies;
SELECT count(*) AS embedded FROM movies WHERE embedding IS NOT NULL;
SELECT count(*) AS with_personality FROM movies WHERE personality IS NOT NULL;
# All three should match.
```

Then open `https://cinemind-web.onrender.com/chat` and try:
*"something like Interstellar but not about space, emotional, mind-blowing
ending"* — you should get ranked cards with explanations.

---

## 7. Environment variables (production)

Set in Render's dashboard (or `.env` locally). Never commit real values.

| Variable | Where | Value / purpose |
| --- | --- | --- |
| `DATABASE_URL` | api | Neon **pooled** URL (app runtime traffic) |
| `DATABASE_URL_DIRECT` | api | Neon **direct** URL (migrations, backfills) |
| `DB_SSL` | api | `require` (any managed Postgres) |
| `JWT_SECRET` | api | Auto-generated by the blueprint |
| `TMDB_API_KEY` | api | TMDb API key |
| `OPENAI_API_KEY` | api | OpenAI (or compatible) key |
| `OPENAI_BASE_URL` | api | `https://api.openai.com/v1` (or your provider) |
| `LLM_MODEL` | api | e.g. `gpt-4o-mini` |
| `EMBEDDING_MODEL` | api | `text-embedding-3-large` |
| `EMBEDDING_DIMENSIONS` | api | `1536` (must match the DB column) |
| `CORS_ORIGINS` | api | Frontend URL, comma-separated |
| `CHAT_RATE_LIMIT_PER_MINUTE` | api | `10` (protects the OpenAI budget) |
| `SEARCH_RATE_LIMIT_PER_MINUTE` | api | `30` |
| `LOG_FORMAT` | api | `json` in production |
| `LOG_LEVEL` | api | `INFO` |
| `NEXT_PUBLIC_API_BASE_URL` | web | Backend URL (baked at build time) |

Full list with local defaults: [backend/.env.example](backend/.env.example),
[frontend/.env.example](frontend/.env.example) (if present).

---

## 8. Monitoring & health

- **Health check**: `GET /health` (also `/api/health`) returns
  `{status, version, database, uptime_seconds, timestamp}` — HTTP 200 even
  when the DB is down (`database: "down"`), so the container reports
  liveness separately from DB health. Render pings it every 30s (free tier:
  on-demand) and restarts the service if it fails.
- **Logs**: `LOG_FORMAT=json` emits one queryable JSON object per line —
  every request logged with `method`, `path`, `status`, `duration_ms`.
  Health-check polls are excluded from the access log.
- **Uptime alerts**: Render dashboard → service → **Alerts** → email on
  failed deploys / health-check failures. For uptime-from-outside, add the
  free [UptimeRobot](https://uptimerobot.com) monitor on `/health`
  (this also keeps a free-tier service from sleeping).
- **Metrics**: Render's **Metrics** tab shows CPU/memory per service; Neon's
  dashboard shows query latency, storage, and autosuspend activity.

---

## 9. Redeploys & updates

- **Auto-deploy**: every push to the connected branch re-builds both images
  and runs migrations first (container entrypoint). If migrations fail,
  the container exits and the deploy is marked unhealthy — the running
  version keeps serving until the new one passes its health check.
- **Manual**: Render dashboard → **Manual Deploy → Deploy latest commit**.
- **Rollback**: service → **Events** → a previous deploy → **Rollback**.
- **Schema changes**: generate locally with
  `alembic revision --autogenerate -m "..."`, commit the file, push. It runs
  on the next deploy automatically.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Backend container exits during boot (migration errors in logs) | Wrong/empty `DATABASE_URL_DIRECT`, or you pasted the **pooled** URL there — Neon's PgBouncer rejects some DDL. Use the direct URL. |
| `password authentication failed` | Copied the Neon URL with the placeholder password, or the role/branch mismatch — copy fresh from Neon's dashboard. |
| Backend boots, `/health` shows `database: "down"` | `DB_SSL` not `require` (Neon closes plaintext connections) or a typo in the host. |
| Frontend loads, all API calls fail | `NEXT_PUBLIC_API_BASE_URL` not set or missing `https://`, or `CORS_ORIGINS` doesn't exactly match the frontend URL (scheme + host + port). Rebuild the frontend after changing either. |
| First request after idle takes ~30s | Free-tier spin-down. Upgrade the service or ping it with UptimeRobot. |
| `/chat/message` returns 429 | Rate limit hit — `CHAT_RATE_LIMIT_PER_MINUTE` in the dashboard (or wait a minute). |
| Search returns empty | Catalog empty or embeddings missing — run §6a/§6b. |

---

## 11. Cost summary

| Item | Plan | Cost |
| --- | --- | --- |
| Neon Postgres | Free tier (0.5 GB, autosuspend) | $0 |
| Render backend + frontend | Free tier ×2 | $0 (with spin-down) |
| Render backend, always-on (optional) | Starter | $7/mo |
| OpenAI LLM + embeddings | Pay-per-use | ~$1-5/mo at hobby scale |
| TMDb | Free tier | $0 |
| **Total (minimum)** | | **$0/mo** |
