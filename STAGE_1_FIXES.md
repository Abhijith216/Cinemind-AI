# Stage 1: confirmed bug fixes

Completed 2026-10-21. This is the first batch from the completeness audit; catalog ingestion and recommendation improvements are separate next stages.

## Changes

- **Truthful taste graph:** only scores of 7 or higher qualify. Movies without a shared genre or keyword are omitted. The five-film limit is applied after finding meaningful connections, so unrelated higher-rated films do not hide a real match. Empty-state text now describes missing connections rather than incorrectly claiming there are no ratings.
- **Movie routes:** malformed links and missing records show a dedicated “Movie not found” page with HTTP 404. Temporary failures use the movie error boundary with a Retry action that makes a fresh GET for the current page. Removed the surrounding loading boundaries so the server can decide the error status before streaming a success response. Next documents the streamed/non-streamed distinction in its [not-found reference](https://nextjs.org/docs/14/app/api-reference/file-conventions/not-found).
- **Chat composer:** the conversation has a bounded viewport and scrolls internally; the composer stays visible. Auto-scrolling targets the conversation instead of moving the outer page. Reduced-motion behavior and keyboard access to the log are preserved.
- **Backend types:** replaced the untyped reference-normalization lambda with a typed function; strict mypy checks pass.
- **Deployment configuration:** standalone tracing is rooted at the frontend, producing the root server.js expected by the Dockerfile. Render and Compose use the same OpenRouter/free settings, structured output, and reasoning configuration as the local setup. The documented Compose command explicitly loads backend/.env for interpolation.

## Verification

- Backend: **219 tests passed**, Ruff passed, mypy passed across 42 source files.
- Frontend: **22 tests passed**, TypeScript and ESLint passed, production build passed. Four optional live suites remain excluded from the default suite.
- Live database graph test: scores 3 and 6 were excluded; an unrelated 10/10 film was excluded; a related 7/10 film was retained; all returned edges had real shared attributes. The disposable account, ratings/profile, and token file were removed.
- Real browser route checks: valid movie 200, malformed link 404, unknown movie 404.
- Real outage recovery: stopped the backend, verified HTTP 500 and the movie error screen, restarted the backend, then confirmed one Retry returned HTTP 200 and loaded Interstellar.
- Browser layout regression using explicit movie-card fixtures: four recommendation turns at 1440×900, 390×844, and 390×600 kept the composer within the viewport and the outer page stationary. The conversation scrolled internally without horizontal document overflow.
- Standalone smoke test: copied the generated bundle and public/static assets into an isolated directory, started its root server.js, and verified both page and asset delivery. This follows the [Next standalone output layout](https://nextjs.org/docs/15/app/api-reference/config/next-config-js/output).
- Compose and Render YAML parsed successfully and their provider settings were checked.

## Limit

Docker is not installed on this computer, so the Docker image itself was not built or executed. The corrected standalone entry point and asset layout were tested directly.

The next stage is catalog freshness and poster coverage. It has not been started.
