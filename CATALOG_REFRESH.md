# Catalog maintenance

Run commands from `backend/`, using the project's Python environment. Credentials stay in `backend/.env`. Apply migrations before starting the job:

```powershell
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.services.catalog_refresh --limit 6000 --pages 15
```

The first command adds nullable TMDb attempt/success timestamps without replacing movies. The second backfills the existing catalog and imports popular, top-rated, and recent released films. Recent discovery covers the last two years; all-time discovery also supplies older films. This is a curated catalog, not the complete TMDb database. Adult, undated, and future titles are excluded from new imports.

## Daily refresh

For local development, keep a separate terminal/process running:

```powershell
..\.venv\Scripts\python.exe -m app.services.catalog_refresh --limit 1000 --pages 10 --interval-hours 24
```

This runs immediately and then waits 24 hours between runs. It stops when the process/computer stops. On a host with a scheduler, run the same command without `--interval-hours` daily. Run only one maintenance worker per database to avoid unnecessary duplicate requests; concurrent upserts are idempotent.

Docker Compose includes an optional persistent maintenance worker:

```sh
docker compose --env-file backend/.env --profile maintenance up --build -d
docker compose --env-file backend/.env logs -f catalog-refresh
```

It waits for the backend's health check after startup migrations, repeats daily, and restarts with Docker. This requires a valid TMDb credential. A Render web service does not run this worker automatically: configure a separate scheduled job or background worker using the same database/TMDb settings. Do not run a daily loop inside the request-serving web process.

## Progress and recovery

- Each 25-movie batch commits metadata and attempt checkpoints together. Restart the same command after interruption; committed/fresh records are skipped for seven days by default (`--stale-days`). New discoveries and unchecked old records both receive capacity in bounded runs.
- The job uses at most eight concurrent detail requests and appends keywords to each detail request. HTTP 429/5xx receive retries/backoff through the TMDb client. See TMDb's [combined-request documentation](https://developer.themoviedb.org/docs/append-to-response) and [discovery parameters](https://developer.themoviedb.org/reference/discover-movie).
- Existing records without a poster, deleted TMDb IDs, and temporary failures are not selected endlessly ahead of unchecked records. Their last attempt is checkpointed; successful metadata updates also set `tmdb_synced_at`. Failed attempts become eligible again after the stale window. Movies/ratings are retained when TMDb returns 404.
- Progress logs show checked, updated, unavailable and failed counts. Each completed run prints a JSON summary containing timestamps and public TMDb failure IDs. No keys, database URLs or user records are logged. An incomplete/failed run exits nonzero in one-shot mode; credential failures abort rather than checkpointing every movie as failed. In loop mode, aborted runs are retried next cycle; individual checkpointed movie failures become eligible after the stale window.
- Database write failures abort the run and roll back the current batch. Previously committed batches remain. Success counters only advance after commit.
- Movie UUIDs, ratings, creation dates and existing personality scores are preserved. Embeddings are invalidated when their source metadata changes. The job does not generate AI personality scores or embeddings.

Verify after a run with database aggregates (poster coverage, latest release year, successful-sync coverage), and exercise Discover and a movie detail page. A TMDb record can legitimately lack artwork, overview, runtime or keywords; the UI must continue to handle missing metadata.
