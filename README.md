# Autocomplete Keyword Research

A local web application for discovering keyword ideas within an existing SEO niche using Google Autocomplete. The frontend uses React, Vite, and Tailwind CSS. The backend uses FastAPI and HTTPX. One in-process asynchronous worker processes at most one active research job at a time.

**Research data lives only in backend memory.** Jobs, queued queries, progress, and keywords disappear when the backend restarts. Export results to CSV before stopping it. The dashboard displays this warning beside the research controls and results.

The Google Suggest endpoint is unofficial. Availability, response format, and localization can change. The application will use conservative request pacing and stop on access restrictions.

## Status and workflow

Planning is documented in `docs/`. Milestone 7 automated, proxy, and live Suggest checks have been run; direct browser interaction and a fresh-machine install remain to be verified. The project is published on GitHub.

## Windows 11 local startup

In the first PowerShell window:

```powershell
cd F:\autocomplete-keyword-research\backend
py -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --reload
```

Open `http://127.0.0.1:8000/api/health`. The response is `{"status":"ok","service":"autocomplete-keyword-research"}`. The optional `APP_ENV` environment variable defaults to `development`; see `backend/.env.example`. The current health endpoint requires no research job.

Run `python -m pytest` from `backend` for the complete mocked backend suite. No database setup is needed for this project.

## Frontend setup and dashboard

In a second PowerShell window:

```powershell
cd F:\autocomplete-keyword-research\frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. The dashboard checks `/api/health` and displays **Backend Connected** or **Backend Unavailable**. Start the backend first for a connected status; use **Retry** after starting it if the first check failed. Enter a seed, choose country and language independently, select expansion methods, then set depth and request budget. Click **Start research**. The dashboard polls progress and results every two seconds while work is active, including the short period when cancellation is finishing an in-flight request. Use **Pause**, **Resume**, or **Cancel** as needed. Click **Export CSV** to save results, then **Clear results** to release the job and start another. A browser refresh restores the current job while the backend keeps running.

Vite proxies `/api` to `http://127.0.0.1:8000` by default. To use another backend address during development, create `frontend/.env.local` with `VITE_BACKEND_URL=http://host:port` (see `.env.example`) and restart Vite. The browser still calls the relative `/api/health` URL. A deployed frontend must be served with `/api` routed to the backend by its web server.

From `frontend`, run `npm.cmd run build` for a production build and `npm.cmd test` for health, form-validation, and API-client tests. The keyword table uses server-side text filtering and 25-item pages; its sort control sorts the current page. A running job can add results between pages. Export a CSV before clearing results or restarting the backend. The app restores the current in-memory job after a browser refresh while the backend remains running.

Stop Vite with **Ctrl+C** in the frontend window. Before stopping FastAPI with **Ctrl+C**, export any results you need. Jobs, pending queries, progress, and keywords exist only in that Python process and disappear when it stops or `--reload` restarts it. CSV files already downloaded remain on your computer. Run only one backend process; multiple Uvicorn workers would each have separate jobs.

## Verification and limits

Run `python -m pytest -q` from `backend`, then `npm.cmd test` and `npm.cmd run build` from `frontend`. These automated checks use mocked Google responses. A single live check with `age calculator`, US/English, depth 1, direct method, and a five-attempt budget succeeded with one actual request and ten suggestions. A separate localhost Vite-proxy workflow passed with mocked responses. Stopping the backend during an active mocked job made the proxy unavailable; after restart, the current-job endpoint returned 404, confirming intentional memory loss. Headless Chromium in this environment did not respond to page commands, so a full browser click-through, visual responsive inspection, console review, and fresh-machine installation have not been signed off.

Google Suggest is unofficial and can change or block requests. The country/language options are hints, not guaranteed personalization. Results are not saved by the app, and page sorting affects only the visible page. The MVP has no login, database, SEO metrics, or AI features.

## Google Suggest client (T2.1)

`app.services.google_suggest.GoogleSuggestClient` uses a reusable `httpx.AsyncClient` connection pool. Call `await client.get_suggestions(query, country="us", language="en")` inside `async with GoogleSuggestClient(...) as client:`. The client sends `client=firefox`, `q`, `gl`, and `hl` as encoded query parameters. Country and language are independent localization hints. It returns only nonempty suggestion strings from the response's second JSON array, keeping Google's order and original text while removing exact duplicates. Generated search inputs are not considered discovered keywords unless Google returns them.

The constructor accepts `timeout` (default 10 seconds), `request_delay` (1.5 seconds between request starts), `max_attempts` (3), and `retry_base_delay` (1 second, doubled for each retry). Transient network errors and HTTP 5xx are retried within that bound. HTTP 429 and 403 stop immediately with specific exceptions; other HTTP errors and malformed replies raise `GoogleSuggestError`. The endpoint is unofficial and may change. Do not use the client to evade throttling or access controls.

From `backend`, run `python -m pytest` for mocked tests without live Google access. An optional **single live query** can be made with:

```powershell
python -m scripts.manual_google_suggest "age calculator" --country us --language en
```

This manual command needs internet access and may fail if Google restricts the endpoint. It was not used for automated verification.

## One-pass keyword expansion (T3.1)

`app.services.keyword_expansion.generate_queries(seed, methods, modifiers=())` yields normalized, unique search inputs in this fixed order: direct seed, A–Z suffix, A–Z prefix, 0–9 suffix, 0–9 prefix, then custom modifier suffix. Select any subset with method names `direct`, `alphabet_suffix`, `alphabet_prefix`, `numeric_suffix`, `numeric_prefix`, and `modifier_suffix`. Custom modifiers are optional text supplied by the caller; there are no built-in English defaults. The first occurrence of a query wins when whitespace or case makes candidates equivalent.

`await collect_suggestions(seed, methods, client, country="us", language="en", modifiers=(), max_requests=500)` performs **one pass only** through those queries. Pass a reusable `GoogleSuggestClient` so it handles pacing and retries. The budget counts attempted expansion queries, including failed ones; the engine stops before generating or requesting another query when the limit is reached. Returned suggestions alone become keywords. The engine deduplicates them using collapsed whitespace and Unicode `casefold()`, preserves the first returned spelling, and records every distinct discovery query and method. Counts and failures remain in the returned in-memory result, which can be discarded or cleared. A 403 or 429 stops the pass immediately; other client errors are recorded and the pass continues.

Run all backend tests from `backend` with `python -m pytest`. Expansion tests use fake or mocked Suggest responses and make no live Google requests. Recursive BFS research, job controls, and CSV export are described below.

## Recursive breadth-first research (T3.4)

`await app.services.recursive_research.research_keywords(seed, methods, client, ...)` runs one sequential research operation in memory. It uses the same selected query expansion methods at each eligible keyword, a FIFO queue, and one reusable `GoogleSuggestClient`. Depth 0 is the seed; querying it and its expansions yields depth-1 suggestions. Eligible suggestions can be queried for depth 2, then 3 and 4. Suggestions at the configured maximum depth are collected but never expanded.

Defaults are `max_depth=2`, `max_requests=500` **actual HTTP attempts including retries**, `max_keywords=10000`, `max_pending_queue=1000`, and `relevance="seed_phrase"`. The client receives the remaining attempt budget, so its retries cannot exceed it. Result counters distinguish attempted, successful, and failed HTTP attempts; `queries_processed` counts distinct search inputs. The stop reason is `completed`, `max_requests`, `max_keywords`, `cancelled`, `rate_limited`, or `access_denied`. `queue_truncated=True` means some new work was dropped because the pending queue reached its limit; already queued work continues.

Relevance controls **which returned suggestions are expanded**, not which suggestions are collected. `seed_phrase` requires the normalized seed phrase to appear in a suggestion. `seed_terms` requires every seed term of at least three characters to appear as a whole whitespace-separated term, in any order. `none` expands every returned suggestion. These simple text rules can miss synonyms, inflections, punctuation variants, and related ideas. Matching is independent of country/language settings. The queue and keyword limits bound memory use when a broad option or many expansion methods are selected.

Pass an optional `asyncio.Event` as `cancel_event`; setting it stops the engine before another query or retry. An in-flight HTTP request may finish first. This function does not create a background job, API route, or persistent history. Call `result.clear()` or discard the result to release its collections. Run `python -m pytest` from `backend` for mocked BFS, retry-budget, and existing tests; no live Google requests are needed.

## In-memory research job manager (T4.1)

`app.research.job_manager.ResearchJobManager` wraps the BFS engine in one background `asyncio.Task`. Call `await manager.start(ResearchConfig(seed="..."))`, then `get_progress()` and `get_results()` to inspect the current job. `pause()`, `resume()`, and `cancel()` control it. `wait_for_completion()` waits for the task when a caller needs that. The research API exposes these operations to the dashboard.

Jobs move through `PENDING`, `RUNNING`, `PAUSED`, and then `COMPLETED`, `CANCELLED`, or `FAILED`. Pause is cooperative: an in-flight request may finish, but the next HTTP attempt waits. Resume continues the same queue and counters. Cancel sets a signal, releases a paused task, and retains partial results. Unexpected background exceptions mark the job `FAILED` with an error message.

Progress includes ID, seed, country/language, status, configured and current depth, current query, actual HTTP attempt counters, unique keywords, pending queries, start/end times, errors, and stop reason. `get_results()` returns the live in-memory result object without copying its keyword collection. The manager retains only the latest job; even after it finishes, `start()` rejects another until `clear()` is called. `clear()` rejects active work and releases finished result collections. Export results before clearing or restarting the backend. No job or result survives process restart, and a single backend process is required.

Run `python -m pytest` from `backend` for deterministic job lifecycle tests using fake or mocked Suggest responses. No live Google request or database is required.

## Research API (T5.1)

Start the single local backend process as above, then use the API from a local client. For example:

```powershell
$body = @{ seed = 'age calculator'; country = 'us'; language = 'en'; max_depth = 2; max_requests = 100; methods = @('direct', 'alphabet_suffix') } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/research' -ContentType 'application/json' -Body $body
Invoke-RestMethod 'http://127.0.0.1:8000/api/research/current'
Invoke-RestMethod 'http://127.0.0.1:8000/api/research/current/keywords?offset=0&limit=50'
Invoke-WebRequest 'http://127.0.0.1:8000/api/research/current/export' -OutFile 'keywords.csv'
```

The start response contains `job_id`, `status`, settings and live counters. `POST /api/research/current/pause`, `/resume`, and `/cancel` control the job. `DELETE /api/research/current` clears a finished job; clear it before starting another. Missing jobs return 404, invalid requests 422, and conflicting states 409. Results remain in memory only, so export before clearing or restarting. See [API design](docs/API_DESIGN.md) and live OpenAPI docs at `http://127.0.0.1:8000/docs`.

## Planned local operation

The MVP will run as one backend process with one asynchronous research worker. Do not run multiple backend workers against independent memory stores. Uvicorn reload restarts the process and discards research data; use it only when that loss is acceptable. Exported CSV files remain wherever the user saves them.
