# Stage 2: catalog refresh complete

Verified on 2026-10-21. Scope: current movie imports, existing metadata/artwork backfill, resumable maintenance and scheduling. Recommendation ranking/personalization remains the next stage.

## Live catalog result

| Metric | Before | After |
| --- | ---: | ---: |
| Movies | 4,803 | 5,333 |
| Poster paths | 48 | 5,313 (99.6%) |
| Releases since 2020 | 0 | 376 |
| Releases since 2025 | 0 | 283 |
| Newest release year | 2017 | 2026 |
| Successful TMDb metadata syncs | Not tracked | 5,325 |
| Records still unchecked | Not tracked | 0 |

The refresh added 530 films. It refreshed 575 records before a deliberate interruption, then resumed with the remaining 4,758 rather than repeating those completed records. The resumed run updated 4,750 and marked eight unavailable, with zero transient failures. Direct source checks confirmed HTTP 404 for all eight unavailable TMDb IDs: 183894, 36597, 333355, 50942, 112430, 153397, 310706 and 395766. Their historical records remain to preserve references and potential ratings.

Twenty movies still have no poster path: those eight unavailable records and twelve successfully synced records whose TMDb details have no poster. The existing UI provides a title fallback. This is a source-data limitation. Runtime is available for 5,329 movies and an overview for 5,332. The catalog is a curated selection, not the entire TMDb database.

## Implementation

- Migration 0004 adds separate nullable attempt/success timestamps without replacing records.
- `app.services.catalog_refresh` discovers popular, top-rated and recent released films; excludes adult/future/undated new imports; and backfills stale existing records. Bounded runs reserve room for both new films and unchecked older films.
- At most eight concurrent detail requests fetch keywords in the same response. Existing rate-limit/network retry behavior is retained.
- Bulk upserts and attempt checkpoints commit together in batches of 25. Committed progress survives restarts. Database errors abort the run; credential errors are not checkpointed as thousands of movie failures. Logs and JSON summaries show progress and public failure IDs without credentials.
- Movie UUIDs, creation dates, linked ratings and existing personality scores are preserved. Changed embedding source metadata invalidates its old embedding.
- A dedicated daily worker and optional Docker Compose `maintenance` profile provide repeatable refreshes. Setup and recovery instructions are in [CATALOG_REFRESH.md](CATALOG_REFRESH.md); README and deployment instructions point to the new job.

## Verification

- Backend: 235 tests passed; Ruff and strict mypy passed. The sixteen new tests cover release/date filtering, request parameters, bounded concurrency, failure isolation, credential rejection, atomic checkpoints, fresh-record skipping/resume, SQL preservation, sanitized failures and daily scheduling.
- Frontend: 22 tests passed, four optional live suites skipped by default; TypeScript, ESLint and production build passed.
- Real browser/API flow at 1440×900 and 390×844: recent-release Science Fiction search returned 2025–2026 films; Discover found Project Hail Mary; the Explore link completed navigation to its movie URL and detail heading; real CDN poster images decoded on both pages; no horizontal overflow or browser page exceptions. Screenshots were inspected.
- Real database bulk-upsert transaction preserved existing movie IDs, creation dates, personality scores and two linked test ratings. All temporary test writes were rolled back, and account removal was verified. The final aggregate/identity audit also confirmed preserved catalog identities/personality data and unchanged existing ratings.
- The daily worker's immediate post-backfill run discovered 444 candidates, selected zero fresh records, updated zero and reported zero failures. It is running locally and waits 24 hours before its next cycle.
- Compose YAML and shared maintenance-worker settings were parsed and checked. Docker is not installed here, so actual container execution remains unverified.

The local daily worker runs only while its process/computer remains running; it is not an installed Windows startup task. For persistent hosting, enable the documented Docker worker or configure a separate scheduled/background job. The Render web service alone does not schedule catalog refreshes.
