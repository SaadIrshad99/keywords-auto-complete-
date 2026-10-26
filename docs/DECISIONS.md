# Architecture decisions

| Decision | Reason and trade-off |
| --- | --- |
| No database or durable store | Keeps the MVP small. Jobs, queue, progress, and keywords disappear on backend restart. CSV is the only supported way to retain results. |
| One backend process and one in-process async worker | Allows direct shared memory and `asyncio.Queue` use. Multiple Uvicorn workers/replicas and a separate worker process are unsupported because they would not share state. |
| Python sets for deduplication | Fast, simple uniqueness checks for queries and normalized keywords. Dictionaries/lists retain metadata and multiple discovery origins. |
| One retained job | Simplifies state and rate control. Starting another job is rejected until the finished job is explicitly cleared, protecting unexported results. |
| Cooperative controls | Pause gates new HTTP attempts, resume continues the same BFS queue, and cancel stops after any in-flight request. Partial results remain in memory until clear or restart. |
| Breadth first expansion | Predictable depth and budget use. The selected methods can apply at each eligible keyword; request and queue limits prevent unbounded growth. |
| Bounded recursive BFS | The selected methods apply at each eligible keyword, with a FIFO queue, one request at a time, and limits for HTTP attempts, queue size, keywords, and depth. Broad methods may fill the queue; the result reports truncation. |
| Attempt-level request accounting | An optional Suggest client callback reports each actual HTTP attempt, including retries. The BFS engine caps each call by the remaining budget. |
| Exact normalized seed phrase relevance for MVP | Deterministic and testable; can omit synonyms, rewordings, and related terms. No AI relevance layer. |
| Conservative Suggest access | The endpoint is unofficial. Use delay, bounded retries, and stop/pause on throttling; never bypass restrictions. |
| Local REST API | One FastAPI process owns one in-memory manager. Pydantic validates incoming settings; 404 and 409 distinguish absent jobs from state conflicts. No public CORS is enabled. |
| CSV export snapshot | Capture scalar discovery rows during a synchronous pass, then stream CSV with UTF-8 BOM. This avoids concurrent mutation during streaming, uses one row per discovery origin, and guards untrusted text against spreadsheet formulas. |
| JavaScript frontend | Keeps initial tooling simple. Revisit TypeScript only if application complexity warrants it. |

## Open decisions before later tasks

- Agree on the supported language/country selector list and translated modifier sets before modifier expansion UI work.
- Review whether the default pending queue limit of 1,000 and keyword limit of 10,000 fit typical local research runs; the HTTP attempt limit remains authoritative.
- The future UI should explain that clearing a finished job permanently removes any unexported results.

The earlier MySQL, SQLAlchemy, Alembic, and persistent worker plan has been superseded. T1.1 contains no database integration and needs no code change for this decision.
