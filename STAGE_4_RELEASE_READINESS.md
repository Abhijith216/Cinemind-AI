# Stage 4: release-readiness and management work

Implemented and verified on 2026-10-21–22. This stage adds management controls and deployment safeguards. Hosted Docker and CI verification passed; the remaining deployment limits below still matter before public release.

## Completed

- **Readiness:** `/ready` and `/api/ready` check required storage/schema within three seconds and return 503 when unavailable. Existing `/health` remains a 200 liveness/diagnostic response. Docker and Render health checks now use `/ready`.
- **Shared protection:** deployment configuration uses `RATE_LIMIT_BACKEND=database`. Atomic PostgreSQL counters enforce per-address, per-route-group minute budgets across processes/replicas. Arbitrary bearer tokens and forwarding headers do not create new identities. Stored keys are HMAC digests; expired counters are pruned. Storage failures fail closed with 503. Memory mode remains a bounded, single-process development option.
- **Search index:** migration 0005 adds a stored, generated weighted `tsvector` and GIN index, and the active search query uses that column. Source metadata changes automatically regenerate it. The approach follows [PostgreSQL's generated-document/index guidance](https://www.postgresql.org/docs/current/textsearch-tables.html#TEXTSEARCH-TABLES-INDEX).
- **Rating management:** owned rating history is paginated in bounded pages, with “Load older ratings” in My Taste. Removing a rating requires confirmation in the UI; deletion and preference rebuild commit together under the same account lock used by rating updates. The live taste timeline derives from remaining ratings.
- **Chat management:** account history lists only the caller's conversations, supports pagination/reopening, and orders by activity. Users can open a saved chat and permanently delete it with confirmation. Database cascades remove its messages. “New chat” keeps earlier conversations. Anonymous current chats can also be deleted using their existing unlisted conversation capability; anonymous chats cannot be enumerated through history.
- **Privacy:** authenticated users cannot append personalized account results to an existing anonymous link. They receive an actionable retry/start-account-chat response instead. Deployment access logs use route templates rather than private record IDs/capabilities; raw uvicorn access logging is disabled in the container entrypoint.
- **Short screens:** fixed an aborted-history refresh that could leave delete/history controls disabled. Added regression coverage. History height and the header now adapt to short viewports so the composer stays visible.
- **CI:** `.github/workflows/verify.yml` includes backend tests/Ruff/mypy, frontend tests/lint/build/types/runtime npm audit, and an isolated Compose/container HTTP smoke job. It uses read-only repository permissions and a CI-only signing secret. Action usage was checked against the official [setup-node](https://github.com/actions/setup-node) and [setup-python](https://github.com/actions/setup-python) examples.
- **Container routing:** `API_INTERNAL_BASE_URL` supplies server-side API routing separately from the browser URL; Compose points it at `http://backend:8000`. This prevents server-rendered movie pages from calling the frontend container's own localhost. Compose requires an explicit JWT secret, and shell scripts are pinned to LF line endings.

## Verification evidence

| Check | Result |
| --- | --- |
| Backend | **270 tests passed**; Ruff and strict mypy passed. Fifteen new regression cases cover readiness, ownership, deletion rollback, pagination, forged identities and anonymous/account separation. |
| Frontend | **28 tests passed**, four optional live suites skipped by default; ESLint, TypeScript and production build passed. Five new cases cover rating history/removal, saved chats/deletion and interrupted history refresh. |
| Live pagination | Seeded 51 ratings in an isolated account; API pages had 50 + 1 distinct rows, and the browser reached the oldest rating. |
| Live rating removal | Browser confirmation returned 204, removed the positive rating, rebuilt preferences to empty likes and removed its personalized suggestions; 50 neutral ratings remained. |
| Live ownership | A second isolated account saw none of the first account's history and could not delete its rating or conversation. |
| Live conversation management | Reopened a saved chat, verified New chat retained it, deleted it through confirmation, verified replay returned 404, and confirmed the other conversation remained. |
| Shared budget | Two independent Python processes admitted exactly 3 of 10 attempts under a shared limit of 3. Temporary counter rows were removed. |
| Forged headers | Real API/database requests with rotating bogus bearer and forwarding headers returned 200, 200, then 429 within one counter window, including Retry-After. |
| Database outage | An isolated app process with an unavailable database returned readiness 503 and liveness 200. The live app returned readiness 200. |
| Indexed search | Unforced `EXPLAIN (ANALYZE, BUFFERS)` used `ix_movies_search_document_gin` for “wormhole”; measured database execution was **1.845 ms** on this catalog. This is one query, not a universal latency claim. Generated-document changes were checked in a rolled-back transaction. |
| Browser layout | Real management flows at 390×844; history-open composer checks at 390×400, 390×480, 390×600, 390×844 and 1440×900 passed without horizontal overflow or browser exceptions. Screenshots were inspected. |
| Configuration | Compose, Render and workflow YAML parsed; internal API and shared-limiter settings checked. Container smoke script compiled. Docker entrypoint LF line endings and `.env` exclusions checked. |

The updated backend (database limiter enabled) and production frontend are running locally. Only isolated QA accounts/records were created or deleted during verification; their ratings, profiles, conversations, messages and local tokens were removed after testing.

## Dependency review

The compatible PostCSS override and lockfile update resolve the runtime npm findings. `npm audit --omit=dev --audit-level=high` reports **zero vulnerabilities**.

The full npm audit still reports **five high development-only entries** in the braces → micromatch → fast-glob → Next ESLint chain. The registry's latest braces version checked was 3.0.3; the [reviewed upstream advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists no patched release. These five entries trace to one upstream vulnerability. npm's proposed fix is a major downgrade to `eslint-config-next@14.2.35`, which does not match this Next 15 app, so it was not applied. These tools process development/lint patterns, not movie requests in the deployed standalone app. CI uses isolated, time-limited jobs with no deployment secrets and audits runtime dependencies. This is an npm exposure review, not a comprehensive security certification or a Python dependency vulnerability scan.

## Deployment and retention decisions

1. **Docker/CI passed on GitHub.** Docker is not installed locally, but the [hosted workflow run](https://github.com/Abhijith216/Cinemind-AI/actions/runs/39736808937) built and started the isolated Compose stack, passed the HTTP smoke flow, and passed backend and frontend jobs. The first run caught a smoke fixture email using the reserved `.invalid` domain; the fixture was corrected and the full workflow rerun passed.
2. **Configure trusted ingress and secrets.** All replicas must share the signing/HMAC secret and use database rate limits. Set `FORWARDED_ALLOW_IPS` to actual trusted proxy addresses/networks; avoid trusting arbitrary client forwarding headers. Without trusted ingress configuration, proxied clients may share a proxy's budget. Use a unique strong JWT secret, correct CORS origins, and the intended browser/internal API URLs. Existing credentials were not changed.
3. **Retention is manual.** Saved conversations remain until explicitly deleted; New chat is not deletion. Account history makes older chats reachable. Anonymous access relies on the unlisted ID retained in the current browser tab; losing it does not automatically remove the server record. No bulk expiry was enabled against existing conversations. Define any future automatic retention period before scheduling deletion.
4. **Earlier limits remain.** Free OpenRouter availability, verified pace/violence/ending coverage, and the optional embedding/personality pipeline are not guaranteed by this stage. Watchlist, richer film details and additional browse controls remain optional next-stage features.
