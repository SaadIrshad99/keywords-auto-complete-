# Research API

Base address for local development: `http://127.0.0.1:8000`. Interactive OpenAPI documentation: `/docs`. Run exactly one backend process. Job data is lost on backend restart or reload.

## Start request

`POST /api/research` accepts JSON:

```json
{
  "seed": "age calculator",
  "country": "us",
  "language": "en",
  "max_depth": 2,
  "max_requests": 500,
  "max_keywords": 10000,
  "max_pending_queue": 1000,
  "request_delay": 1.5,
  "methods": ["direct", "alphabet_suffix"],
  "modifiers": [],
  "relevance": "seed_phrase"
}
```

Only `seed` is required. Country is a two-letter code and language is a two or three letter code with optional region suffix. Codes are sent as independent Google `gl` and `hl` hints; Google may interpret them differently. Depth is 1–4. Budgets and queue/keyword limits must be positive. Delay is 0–60 seconds; the default is 1.5 seconds. Methods are `direct`, `alphabet_suffix`, `alphabet_prefix`, `numeric_suffix`, `numeric_prefix`, and `modifier_suffix`; select at least one. `modifier_suffix` requires custom `modifiers`. Relevance is `seed_phrase`, `seed_terms`, or `none`.

A successful start returns 201 with job ID, status, seed, locale, configuration limits, methods, current depth/query, request counters, keyword count, queue count, timestamps, stop reason, error message, and queue truncation flag. The job may already be running or finished by the time the response arrives. Duplicate starts return 409 until the prior job is cleared.

## Endpoints

| Method | Path | Result |
| --- | --- | --- |
| POST | `/api/research` | Start job, 201 |
| GET | `/api/research/current` | Current progress, 200 |
| POST | `/api/research/current/pause` | Pause new HTTP attempts, 200 |
| POST | `/api/research/current/resume` | Continue same queue, 200 |
| POST | `/api/research/current/cancel` | Stop and retain partial results, 200 |
| GET | `/api/research/current/keywords` | Current keywords, 200 |
| GET | `/api/research/current/export` | CSV download, 200 |
| DELETE | `/api/research/current` | Clear finished job, 204 |

Absent job: 404. Invalid body/query: 422. Conflicting state or uncleared job: 409. Pause is cooperative; an in-flight request can complete. Cancelled or failed jobs retain results until cleared. `CANCELLED` can appear before the in-flight task has ended; wait for `ended_at` before clearing. Clear rejects active or paused jobs and jobs still stopping.

## Keywords and export

`GET /api/research/current/keywords?offset=0&limit=50&filter=calculator` returns `total`, `offset`, `limit`, and `items`. `limit` is 1–200. The optional filter is a case-insensitive substring of original keyword text. Insertion order is stable for collected keywords. Each item includes original text, first depth/query/method, and all distinct discovery paths with parent, query, method, and depth. A running job's results can change between pages.

Export contains one row per discovery path with Keyword, Depth, First Discovery Query, Expansion Method, and Discovery Queries columns. It is streamed as UTF-8 with BOM, correctly CSV quoted, and prefixes a single quote to text cells that could be treated as spreadsheet formulas. It captures current rows before streaming so an export during research is a consistent partial snapshot. Large exports temporarily allocate one scalar row tuple per discovery path. Save the file before clearing or restarting; there is no persistent history.
