# Stage 3: recommendation ranking and personalization complete

Verified on 2026-10-21. Scope: shared taste scoring, chat ranking, supported request constraints, My Taste explanations, replay grounding and provider diagnostics. Sign-in implementation is unchanged.

## Behavior

- Chat now uses the authenticated user's rating history to rerank eligible catalog candidates. Anonymous searches retain catalog order. Already-rated films are excluded, including ratings outside the scoring window.
- Chat and My Taste share the same metadata affinity component. Ratings 7–10 provide positive signals, 1–4 negative signals, and 5–6 no preference. Conflicting ratings balance per genre/theme. Current saved scores and current movie metadata are used, so corrected ratings remove stale signals.
- Hard genre, runtime, release-period and exclusion filters run before personalization. Personal taste cannot admit a candidate that failed those filters. Runtime-only requests can now browse eligible movies rather than returning an empty list immediately.
- My Taste suggestions include an explanation, matched attributes and a preference score. Cards render the explanation and a working “Why this?” control. Empty-state wording also handles existing ratings without eligible suggestions.
- Liked-film explanations consistently use the 7+ threshold. Restored private chat cards use their owner's taste context; saved result order and reply notices remain intact. Explanations on replay reflect current ratings/metadata rather than an immutable historical snapshot.
- Release periods support a year, decade, year range, and “recent” (current year minus five onward). Unrecognized periods are disclosed in the reply. The AI prompt distinguishes release dates from historical story settings.
- Pace and scene-level violence are **not verified by this catalog**. Chat replies explicitly state that those preferences could not be enforced. Ending preferences are identified as theme matches rather than verified endings. These disclosures are also stored in the conversation and survive reloads.
- Provider logs now include attempt, duration, HTTP status and failure category without prompt text, response bodies, API keys or user records. The server's 40-second chat deadline precedes the chat client's 75-second deadline, allowing a controlled error response. Existing bounded retries and retry UI remain.

## Ranking bounds

The scorer uses up to 500 recent ratings and 80 keyword weights. Genre affinity contributes 65%, keyword affinity 35%; the signed result lies in [-1, 1]. My Taste ranks unrated positive-affinity films using that component. Chat reranks up to 100 already-filtered candidates using `1 / (1 + catalog_position / 10) + 0.35 * affinity`. These are ordering scores, not probabilities or content-safety assessments. This is metadata personalization, not a completed embedding-based recommender.

## Verification

- Backend: **255 tests passed**, including 20 new regression cases; Ruff and strict mypy passed.
- Frontend: **23 tests passed**, four optional live suites skipped by default; TypeScript, ESLint and production build passed. The new frontend test verifies factual recommendation text and the matched-attribute drawer.
- Live database/API checks saved a high Interstellar rating and low Saw rating in an isolated account. For the same eligible candidate pool, the first five changed from Snowpiercer / Project Hail Mary / Her / Men in Black / Terminator 2 to Project Hail Mary / Snowpiercer / Her / Men in Black / The Fifth Element. Rated films stayed excluded and all requested filters held.
- The SQL and Python affinity calculations agreed across 30 real catalog movies. The live My Taste API returned six suggestions with explanations and structured matches.
- Real browser checks at **1440×900** and **390×844** verified My Taste explanations, “Why this?” attributes, a decoded live poster, and no horizontal overflow. Screenshots were inspected.
- Two real OpenRouter chat turns each returned five recommendations. Both preserved Comedy/no Horror and the 2025–2026 release range; the second narrowed runtime from 130 to 110 minutes. Pace/violence notices were visible in the replies. Reload restored both recommendation turns and their notices; the mobile composer remained visible. No browser page exceptions were recorded.
- The production frontend and updated backend are running locally. The isolated test account, its ratings/profile and conversation were removed after verification; unrelated accounts/data were left alone.

## Remaining limits and next stage

Genre filtering follows TMDb classifications; it does not certify scene content. Verified pace, violence and ending data remain unavailable. OpenRouter's free router can still suffer upstream capacity/rate-limit failures; these successful live checks do not establish continuous availability, and no paid fallback was enabled. A stable provider/model policy remains a production-readiness decision.

The next stage is release readiness: readiness checks, abuse protection, continuous verification, dependency review, search-index measurements, and rating/chat management gaps from the original audit.
