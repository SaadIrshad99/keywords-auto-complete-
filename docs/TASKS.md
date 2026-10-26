# Implementation tasks

T1.1–T1.3, T2.1, T3.1, T3.4, T4.1, T5.1, T6.1, and T7.2 have been implemented and verified. T7.1, T7.3, and T7.4 still need direct browser or fresh-machine verification as noted below. A task is done when its acceptance criteria hold, its stated tests pass, relevant docs are updated, and changes are reviewed. No task implies permission to commit.

## Milestone 1 — Project Foundation (3 tasks)

- [x] **T1.1 — Backend Project Foundation.** Objective: start a minimal API. Scope/files: `backend/app/main.py`, health route, simple environment config, requirements, example env, test, README. Depends: planning setup. Accept: `GET /api/health` returns HTTP 200 and exact service/status JSON with no external service. Test: Pytest endpoint test and local startup check.
- [x] **T1.2 — Frontend foundation.** Objective: start React locally. Scope/files: Vite React JavaScript app, Tailwind setup, health status, and development proxy. Depends: T1.1. Accept: homepage renders and reports connected or unavailable backend state. Test: `npm install`, build, Node health tests, dev server and proxy smoke checks.
- [x] **T1.3 — Research settings validation.** Objective: define clear local research configuration. Scope/files: Pydantic validation/defaults for seed, locale, depth, budget, delay, and methods. Depends: T1.1. Accept: invalid settings give 422 with clear errors and documented defaults. Test: API validation tests.

## Milestone 2 — Google Suggest Client (1 task)

- [x] **T2.1 — Google Suggest API client.** Objective: retrieve actual suggestions with controlled asynchronous requests. Scope/files: HTTPX client, encoded query/country/language parameters, parsing/deduplication, pacing, bounded retries, 403/429 handling, optional single-query script, and mocked tests. Depends: T1.1. Accept: returns original nonempty suggestions in order, rejects malformed/error responses, and never retries access restrictions. Test: all backend Pytest tests plus optional manual single query.

## Milestone 3 — Keyword Expansion Engine (2 tasks)

- [x] **T3.1 — One-pass keyword expansion.** Objective: generate selected expansion queries and collect actual Suggest results in memory. Scope/files: normalization, direct/A–Z/numeric prefix and suffix generators, optional modifier suffixes, deterministic deduplication, discovery paths, counters, request budget, and mocked tests. Depends: T2.1. Accept: no recursive work, no request beyond budget, original returned keyword text and all distinct origins retained. Test: Pytest expansion and existing backend suite.
- [x] **T3.4 — Recursive BFS research.** Objective: recursively discover suggestions across depths 1–4. Scope/files: FIFO traversal, relationships, deduplication, selected expansion methods, relevance options, actual HTTP-attempt budget including retries, queue/keyword limits, cancellation signal, and mocked tests. Depends: T3.1. Accept: deterministic lower-depth-first processing; no expansion past maximum depth or request budget; safe reported limits. Test: complete backend Pytest suite with depth, failure, budget, cancellation, and locale cases.

## Milestone 4 — In-Memory Jobs and Background Worker (1 task)

- [x] **T4.1 — In-memory research job manager.** Objective: run the existing BFS engine as one background job with live progress. Scope/files: job states and transitions, one `asyncio.Task`, cooperative pause/resume/cancel, partial results, explicit clear, concurrency lock, progress snapshots, and mocked lifecycle tests. Depends: T3.4. Accept: one retained job until clear; valid transitions; live counters; no lost partial results on cancel; failure and restart limitations documented. Test: complete backend Pytest suite with lifecycle, concurrency, pacing, and cleanup cases.

## Milestone 5 — Backend APIs (1 task)

- [x] **T5.1 — Research API milestone.** Objective: expose the in-memory job manager to the local frontend. Scope/files: validated start/status/pause/resume/cancel/clear routes, paginated and filterable keywords, streamed UTF-8 BOM CSV, OpenAPI docs, and mocked API tests. Depends: T1.3, T4.1. Accept: 201 start, 200 reads/actions, 204 clear, 404 missing, 409 conflicts, 422 validation; stable results order; one formula-safe CSV row per discovery origin; partial export while active. Test: complete backend Pytest suite including concurrent start, lifecycle, pagination, filtering, and CSV cases. Consolidates former T5.1–T5.4 by user direction.

## Milestone 6 — React Dashboard (1 task)

- [x] **T6.1 — Research dashboard.** Objective: configure and manage one local job, browse suggestions, and retain CSV. Scope/files: form with locale, depth, budget, methods, modifiers and advanced limits; backend health and restart-loss warning; job polling and controls; server-side keyword filtering/pagination, current-page sorting and metadata; CSV download and clear confirmation. Depends: T1.2, T5.1. Accept: validated settings and visible errors; status, counts, depth and current query; pause/resume/cancel; bounded pages and all discovery paths; CSV works while active or finished; refresh restores the current in-memory job. Test: frontend build, health/form/API-client tests and backend suite. Consolidates former T6.1–T6.4 by user direction.

## Milestone 7 — Integration and Testing (4 tasks)

- [ ] **T7.1 — Local full flow.** Objective: verify UI/API/worker integration in one backend process. Scope/files: integration fixtures and run guide. Depends: milestones 1–6. Accept: create, finish, inspect, and export a job locally. Test: mocked Suggest end to end flow. **Evidence:** API and Vite proxy flow passed, including pause/resume/cancel, partial export, clear, and a second completed job. **Remaining:** direct browser click-through; headless Chromium did not respond to page commands in this environment.
- [x] **T7.2 — Failure and control scenarios.** Objective: exercise timeout, throttling, malformed replies, pause, cancellation, and process restart data loss. Scope/files: scenario tests. Depends: T7.1 implementation. Accept: clear status, bounded requests, and documented loss of memory on restart. Test: existing client/BFS/job/API suites plus mocked workflow and new-app restart check. Browser-facing error rendering has a static render check and API-client error tests; direct browser review remains under T7.1.
- [ ] **T7.3 — Performance and limits.** Objective: verify bounded queue and responsive UI. Scope/files: synthetic load checks and tuning notes. Depends: T7.2. Accept: request/depth limits hold on dense graph. Test: deterministic load simulation. **Evidence:** dense-graph test and depth 1–4 suite pass. **Remaining:** visual responsive and console inspection in a working browser.
- [ ] **T7.4 — Documentation and release review.** Objective: make single-process local setup reproducible. Scope/files: README and worker/run guides. Depends: T7.3. Accept: clean setup instructions and CSV/data-loss behavior are verified; MVP exclusions remain intact. Test: follow guide on fresh local environment. **Evidence:** local servers and proxy flow passed; README updated. **Remaining:** follow the guide on a fresh Windows setup.
