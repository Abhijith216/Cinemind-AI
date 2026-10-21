# CineMind completeness audit

Date: 2026-10-21. Scope: frontend, backend, catalog, recommendation behavior, operations, and release readiness. Sign-in and registration are excluded. A disposable account was used only to exercise ratings and taste features, then removed.

Update: stages 1–4 have been implemented and locally verified. See [STAGE_1_FIXES.md](STAGE_1_FIXES.md), [STAGE_2_CATALOG.md](STAGE_2_CATALOG.md), [STAGE_3_RECOMMENDATIONS.md](STAGE_3_RECOMMENDATIONS.md) and [STAGE_4_RELEASE_READINESS.md](STAGE_4_RELEASE_READINESS.md) for current behavior, evidence and remaining limits. The findings below preserve the original audit baseline. Docker/hosted-CI execution, deployment-specific configuration and unpatched development dependency advisories still need attention before a public release. Unverified pace/violence/ending preferences are disclosed rather than presented as enforced.

## Verdict

The core application is implemented and useful, but it is not complete or ready to describe as a finished production movie finder. The largest gaps are catalog freshness/coverage, recommendation behavior, several user-facing defects, and deployment configuration. There is no agreed final acceptance checklist, so this audit uses the features described by the UI and README as the baseline.

## Verified working

| Flow | Evidence |
| --- | --- |
| Discover | Real browser search for cozy comedy with Comedy and 90-minute filters returned 12 cards and working detail links. Existing tests cover loading, duplicate submissions, empty states, errors, and retry. |
| AI service | A real OpenRouter structured-intent request succeeded. A browser conversation returned five recommendations on each of two turns while keeping Comedy/no Horror and narrowing runtime from 90 to 80 minutes. |
| Conversation recovery | A separate browser restored both recommendation turns from the persisted audit conversation without making another AI request. |
| TMDb | Real movie details, keywords, and poster lookup succeeded. Exact-title lookup and import code exists. |
| Ratings and My Taste | The live component/API/database test saved 9/10, updated preferences and recommendations, restored the rating, changed it to 3/10, and cleared the old likes/timeline correctly. |
| Layout | Main public pages and signed-in taste/movie pages fit 390 px and 1440 px browser viewports without document horizontal overflow. No browser page exceptions were observed in the audit. |
| Automated checks | Backend: 216 tests passed; Ruff passed. Frontend: 19 default tests passed, TypeScript and ESLint passed. The latest production build from the preceding implementation passed and is serving locally. |

Passing tests do not establish catalog completeness, recommendation relevance, deployment correctness, or external-provider reliability.

## Finish before calling the core product complete

| Priority | Gap | Frontend impact | Backend work |
| --- | --- | --- | --- |
| High | Catalog is an old starter snapshot | Most results have title fallbacks; recent-film discovery is largely empty. | Read-only database audit found 4,803 movies, 48 poster paths (about 1%), zero releases since 2020, and newest release year 2017. Import current movies, backfill artwork/details, and schedule refreshes with progress/failure reporting. |
| High | Parsed preferences are only partly applied | Requests about pace or violence can appear accepted without being enforced. | The active catalog path uses mood/themes/genres/reference titles/runtime and limited year handling. Pace and violence tolerance are not used. Implement supported scoring/filtering from reliable metadata, or explicitly explain unsupported constraints instead of silently ignoring them. |
| High | Main chat ranking does not use taste history | A personal profile does not meaningfully change the candidate ranking in chat. | [chat_search.py](backend/app/services/chat_search.py:21) accepts user_id but does not use it; user_history_match is always zero. Taste can affect explanations, and My Taste has its own separate ranking, but these are not one consistent personalized recommender. |
| High | AI reliability remains inconsistent | A follow-up may fail even when a previous turn worked. | One live two-turn test failed to produce its second result set. A separate real browser run passed both turns. The failure is intermittent; the first failure's exact provider response was not captured. Add structured timing/failure-category telemetry, stable model selection/fallback policy, and provider failure tests before claiming reliability. |
| High | Recommendation graph mislabels disliked films | “You loved” can show a 3/10 film and an edge with no shared attributes. | [graph.py](backend/app/services/graph.py:63) selects the top five ratings without a liked threshold and creates edges even when both intersections are empty. The audit reproduced both behaviors using its disposable account. Filter liked ratings and meaningful shared connections. |
| Medium | Movie errors bypass the useful error boundary | Invalid or missing movie URLs show a generic sentence, no movie heading, and no retry button. | [movie page](frontend/src/app/movie/[id]/page.tsx:19) catches all failures. Browser checks for malformed and nonexistent IDs returned HTTP 200. Distinguish not-found from an unavailable backend; use the route's not-found/error behavior and a real retry action. |
| Medium | Chat composer moves below the viewport | After two recommendation turns its top was at 1,014 px in a 900 px viewport. The user must scroll to continue. | Give chat a bounded conversation region or sticky composer. Keep keyboard/mobile behavior and reduced motion working. |
| Medium | Personalized suggestions do not explain their selection | My Taste cards display “No explanation available yet.” | Return a factual explanation and matched attributes from taste-dashboard ranking, then render them in the existing cards. |
| Medium | Rating history cannot be fully managed | Only the newest 50 ratings are available; ratings can be edited but not removed. | Add paginated history and a rating-delete operation that rebuilds preferences atomically. The current endpoints are POST/upsert and GET only. |

## Release and backend readiness

1. **Container layout needs correction and verification.** The current standalone output is at `frontend/.next/standalone/frontend/server.js`, while [frontend/Dockerfile](frontend/Dockerfile:42) starts `node server.js` from the copied standalone root. `outputFileTracingRoot` points above the frontend. The container entry point and static/public copy paths must agree with the actual output. Docker is unavailable on this computer, so a container build/run could not be executed; this is a configuration finding, not a verified container runtime result.
2. **Provider configuration has drifted.** Local setup uses OpenRouter/free, but [render.yaml](render.yaml:43) configures the OpenAI endpoint and gpt-4o-mini. Docker Compose also defaults to the OpenAI endpoint and does not pass all current LLM settings. Make deployment configuration reproduce the chosen local setup.
3. **Backend type checking currently fails.** Mypy reports two `no-untyped-call` errors at query_understanding.py:160–161 from the untyped normalization lambda. Tests and Ruff pass; this quality gate does not.
4. **Dependency review remains open.** The current npm audit reports seven advisories: six high and one moderate, including transitive tooling and PostCSS paths. Assess actual runtime exposure and compatible upgrades; do not apply the suggested breaking/downgrade fixes blindly. Detailed local output is in ignored `tmp/completeness-npm-audit.json`.
5. **Health is liveness, not readiness.** /health returns 200 even when database is down, while deployment uses it as its health check. Add a separate readiness response that fails when required storage is unavailable.
6. **Production abuse protection is incomplete.** The limiter is per-process, keeps client keys in memory, and keys public Discover requests from an unverified Bearer header when supplied. Arbitrary changing headers can avoid that per-key limit. Use a verified identity or trusted client address and a shared limiter before scaling or public exposure.
7. **No continuous verification pipeline was found.** Add CI for backend tests/Ruff/mypy, frontend tests/types/lint/build, and a container smoke test. The four live suites are opt-in, so default green tests do not prove that providers and database work.
8. **Search scaling needs an index plan.** The database has genre/keyword GIN indexes and an embedding index, but no full-text index matching the document built by catalog_search. At the current small size it works; expanding the catalog should include a matching stored/expression search index and measured query plans.
9. **Legacy semantic search is not ready.** There are zero movie embeddings and only 48 movie personality records. The active UI uses metadata search, so this does not block basic Discover/chat. The existing hybrid/semantic pipeline must not be counted as a completed live feature until its provider, backfill, coverage, and relevance are verified.
10. **No chat management/retention policy exists.** New chat removes the browser's selected session but does not delete the saved conversation. There is no conversation list, deletion endpoint, or scheduled expiry. Define retention and provide deletion/history controls if saved conversations are part of the finished product.

## Suggestions, rather than defects in an agreed requirement

- Add a watchlist/save-for-later flow. Discover currently uses the phrase “From thought to watchlist” without an implemented watchlist.
- Expose language, release year, and minimum-rating controls that the backend already supports. Persist the request and filters in the URL so Back/reload can recover a search.
- Offer a useful initial browse shelf and clear supported-request examples; currently the homepage is mainly search plus explanatory content.
- Add cast/director, trailers, and region-specific watch-provider links after verifying their data and attribution requirements. These are useful product additions, not prerequisites for basic movie finding.
- Add result pagination/load-more, conversation history, keyboard/accessibility checks, and a relevance evaluation set with expected constraints. Automated pass/fail tests alone cannot judge whether the picks are good.
- Make provider outages actionable: preserve the draft/request, allow retry, and link directly to a catalog-search alternative.

## Recommended completion sequence

1. Correct the graph, movie error states, composer, type-check failures, and mismatched deployment configuration.
2. Refresh the catalog and posters; add recurring ingestion/refresh monitoring.
3. Unify recommendation ranking and explanations, enforce supported preferences, and measure a fixed set of real requests.
4. Add deletion/history management, CI, readiness and abuse protection; run deployment smoke tests.
5. Add watchlist and richer movie details if those are part of the desired first release.

The application was not changed during this audit. Only audit notes and ignored verification helpers were added. The disposable taste account, its ratings/profile, and its local token were removed.
