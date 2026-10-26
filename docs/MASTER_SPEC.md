# Master specification

## Purpose and scope

Discover Google Autocomplete suggestions for a supplied seed in an already selected niche. Users configure country, language, depth (1–4), request budget, pacing, and expansion methods; monitor a job; pause or cancel it; search current results; and export CSV. No login or authentication is included. This tool does not estimate search volume, difficulty, ranking opportunity, or niche quality.

## Functional requirements

- Validate nonempty seed, supported country/language codes, depth 1–4, positive request limit, nonnegative delay, and at least one expansion method. Suggested defaults: depth 2, request limit 500, concurrency 1, delay 1–2 seconds.
- Query the unofficial Google Suggest endpoint with URL encoded `q`, language hint `hl`, country hint `gl`, and `client=firefox`. Parse the expected JSON array safely; tolerate empty/malformed replies, timeouts, and HTTP errors.
- Support direct seed, alphabet suffix/prefix, digit suffix/prefix 0–9, and configurable language appropriate modifier suffixes. Only suggestions returned by Google become discovered keywords; generated queries are work items. The first expansion pass is independent of later recursive BFS work.
- Use breadth first recursion. Depth 0 is the seed. Depth 1 is suggestions from initial seed expansions. Depth 2–4 are suggestions from eligible prior depth keywords. Suggestions at maximum depth are collected but not expanded. Enforce depth and an attempt-level request budget, including retries, before each HTTP call. Bound unique keywords and pending queue size.
- Use Python sets to deduplicate normalized query strings and keywords. Keep original text, country, language, depth, parent query, method, and discovery time in in-memory result records. Retain distinct discovery origins without duplicate keyword entries.
- Hold one job's configuration, FIFO pending work, progress, results, and errors in backend memory. The research engine uses a bounded `deque`; a background `asyncio.Task` runs it in the same process. Support one active job, basic pause/resume/cancel controls, and progress counts. Pausing is cooperative between HTTP attempts; cancellation stops further attempts and retains collected results until cleared or restart. A finished job must be cleared before another starts.
- Provide a React dashboard with configuration, progress, searchable/sortable/filterable current results, and CSV export. Show a clear warning that results not exported to CSV will be lost on backend restart. Do not promise research history or recovery after restart.
- Export UTF-8 CSV. If a keyword has multiple discovery origins, export one row per origin with repeated keyword text and document that behavior. Neutralize spreadsheet formulas in all untrusted text cells.

## Reliability and limits

Use bounded retries with exponential backoff for transient failures. Pause or stop on 429/403 and never evade CAPTCHA, IP restrictions, or access controls. Localization parameters are hints, not exact personalization. Configurable seed phrase, meaningful-term, or no relevance filtering controls recursive expansion. Text rules can miss synonyms, inflections, and related ideas. Avoid duplicate query requests within a research run. Use structured logs without credentials or unnecessary personal data. Worker failure marks the job failed when caught; process termination loses all in-memory state.

## Technology and operation

Frontend: React, Vite, Tailwind CSS, JavaScript. Backend: Python, FastAPI, HTTPX, `asyncio.Queue`, Python sets and dictionaries. Tests: Pytest with mocked Suggest responses and lightweight frontend tests. Run a single backend process and a single worker task for the MVP. Multiple Uvicorn workers or replicas would hold separate, inconsistent state and are unsupported. Future deployment may use a single process behind a reverse proxy; no database or durable store is planned.

## MVP exclusions

No database of any kind, SQLAlchemy, Alembic, persistent history, restart recovery, login/authentication, AI/LLMs, semantic clustering, difficulty or volume estimates, SERP scraping, competitor analysis, content planning/generation, paid proxies, CAPTCHA bypass, or distributed workers.

## Acceptance criteria

An operator can create a valid job, observe bounded and paced BFS collection, pause or cancel it, browse unique current suggestions, and export safe UTF-8 CSV. The UI clearly warns about data loss on restart. Automated tests cover parsing, expansion, BFS order/depth/budget, deduplication, queue behavior, pause/cancel, API validation, and export using mocked Google replies. The default automated suite makes no live Google calls. Restarting the backend intentionally clears all jobs and results.
