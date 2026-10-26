"""Bounded breadth-first keyword research using the existing Suggest client."""

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from app.services.google_suggest import (
    GoogleSuggestAccessDenied,
    GoogleSuggestCancelled,
    GoogleSuggestClient,
    GoogleSuggestError,
    GoogleSuggestRateLimited,
)
from app.services.keyword_expansion import (
    ExpansionQuery,
    generate_queries,
    keyword_key,
    normalize_whitespace,
)


@dataclass(frozen=True)
class ResearchQuery:
    text: str
    method: str
    parent_keyword: str
    depth: int


@dataclass(frozen=True)
class ResearchDiscovery:
    parent_keyword: str
    query: str
    method: str
    depth: int


@dataclass
class ResearchKeyword:
    text: str
    first_depth: int
    discoveries: list[ResearchDiscovery] = field(default_factory=list)


@dataclass
class ResearchResult:
    keywords: dict[str, ResearchKeyword] = field(default_factory=dict)
    expanded_keywords: set[str] = field(default_factory=set)
    requested_queries: set[str] = field(default_factory=set)
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    queries_processed: int = 0
    pending_queries: int = 0
    current_query: str | None = None
    current_depth: int = 0
    failures: list[str] = field(default_factory=list)
    stop_reason: str = "completed"
    queue_truncated: bool = False

    @property
    def unique_keywords_discovered(self) -> int:
        return len(self.keywords)

    def clear(self) -> None:
        """Release collections when a future job manager replaces this research."""
        self.keywords.clear()
        self.expanded_keywords.clear()
        self.requested_queries.clear()
        self.failures.clear()


def _eligible(keyword: str, seed: str, relevance: str) -> bool:
    if relevance == "none":
        return True
    normalized_keyword = keyword_key(keyword)
    normalized_seed = keyword_key(seed)
    if relevance == "seed_phrase":
        return normalized_seed in normalized_keyword
    terms = [term for term in normalized_seed.split() if len(term) >= 3]
    return all(term in normalized_keyword.split() for term in terms) if terms else normalized_seed in normalized_keyword


async def research_keywords(
    seed: str,
    methods: tuple[str, ...] | list[str],
    client: GoogleSuggestClient,
    *,
    country: str = "us",
    language: str = "en",
    modifiers: tuple[str, ...] | list[str] = (),
    max_depth: int = 2,
    max_requests: int = 500,
    max_keywords: int = 10000,
    max_pending_queue: int = 1000,
    relevance: str = "seed_phrase",
    cancel_event: asyncio.Event | None = None,
    pause_event: asyncio.Event | None = None,
    result: ResearchResult | None = None,
    on_progress: Callable[[ResearchResult], None] | None = None,
) -> ResearchResult:
    """Collect suggestions at depths 1–4 with one sequential FIFO traversal.

    The request budget counts each HTTP attempt, including retries. A full
    queue truncates new work but lets already queued work finish.
    """
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 1 <= max_depth <= 4:
        raise ValueError("max_depth must be an integer from 1 to 4")
    for name, value in (
        ("max_requests", max_requests),
        ("max_keywords", max_keywords),
        ("max_pending_queue", max_pending_queue),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if relevance not in {"seed_phrase", "seed_terms", "none"}:
        raise ValueError("relevance must be seed_phrase, seed_terms, or none")

    normalized_seed = normalize_whitespace(seed)
    initial_queries = generate_queries(normalized_seed, methods, modifiers)
    result = result if result is not None else ResearchResult()
    if result.queries_processed or result.requests_attempted or result.keywords:
        raise ValueError("result must be unused")
    result.expanded_keywords.add(keyword_key(normalized_seed))
    queue: deque[ResearchQuery] = deque()
    scheduled: set[str] = set()

    def enqueue(parent: str, depth: int, query: ExpansionQuery) -> bool:
        key = keyword_key(query.text)
        if key in scheduled:
            return True
        if len(queue) >= max_pending_queue:
            result.queue_truncated = True
            return False
        queue.append(ResearchQuery(query.text, query.method, parent, depth))
        scheduled.add(key)
        result.pending_queries = len(queue)
        return True

    for query in initial_queries:
        if not enqueue(normalized_seed, 1, query):
            break

    def record_attempt(succeeded: bool) -> None:
        result.requests_attempted += 1
        if succeeded:
            result.requests_succeeded += 1
        else:
            result.requests_failed += 1
        if on_progress is not None:
            on_progress(result)

    async def wait_for_resume() -> None:
        if pause_event is None or pause_event.is_set():
            return
        if cancel_event is None:
            await pause_event.wait()
            return
        resume_task = asyncio.create_task(pause_event.wait())
        cancel_task = asyncio.create_task(cancel_event.wait())
        try:
            await asyncio.wait(
                {resume_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (resume_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(resume_task, cancel_task, return_exceptions=True)

    while queue:
        await wait_for_resume()
        if cancel_event is not None and cancel_event.is_set():
            result.stop_reason = "cancelled"
            break
        if result.requests_attempted >= max_requests:
            result.stop_reason = "max_requests"
            break

        work = queue.popleft()
        result.pending_queries = len(queue)
        result.current_query = work.text
        result.current_depth = work.depth
        result.requested_queries.add(keyword_key(work.text))
        result.queries_processed += 1
        if on_progress is not None:
            on_progress(result)
        try:
            request_options = {
                "max_attempts": max_requests - result.requests_attempted,
                "on_attempt": record_attempt,
                "should_stop": cancel_event.is_set if cancel_event is not None else None,
            }
            if pause_event is not None:
                request_options["before_attempt"] = wait_for_resume
            suggestions = await client.get_suggestions(
                work.text,
                country=country,
                language=language,
                **request_options,
            )
        except GoogleSuggestCancelled:
            result.stop_reason = "cancelled"
            break
        except GoogleSuggestError as exc:
            result.failures.append(f"{work.text}: {exc}")
            if isinstance(exc, GoogleSuggestRateLimited):
                result.stop_reason = "rate_limited"
                break
            if isinstance(exc, GoogleSuggestAccessDenied):
                result.stop_reason = "access_denied"
                break
            if on_progress is not None:
                on_progress(result)
            continue

        for suggestion in suggestions:
            if not isinstance(suggestion, str) or not suggestion.strip():
                continue
            key = keyword_key(suggestion)
            discovery = ResearchDiscovery(work.parent_keyword, work.text, work.method, work.depth)
            keyword = result.keywords.get(key)
            if keyword is None:
                if len(result.keywords) >= max_keywords:
                    result.stop_reason = "max_keywords"
                    result.current_query = None
                    result.pending_queries = 0
                    if on_progress is not None:
                        on_progress(result)
                    return result
                keyword = ResearchKeyword(suggestion, work.depth, [discovery])
                result.keywords[key] = keyword
            elif discovery not in keyword.discoveries:
                keyword.discoveries.append(discovery)
                keyword.first_depth = min(keyword.first_depth, work.depth)

            if work.depth >= max_depth or key in result.expanded_keywords:
                continue
            if not _eligible(suggestion, normalized_seed, relevance):
                continue
            result.expanded_keywords.add(key)
            for query in generate_queries(suggestion, methods, modifiers):
                if not enqueue(suggestion, work.depth + 1, query):
                    break
        if on_progress is not None:
            on_progress(result)

    result.current_query = None
    result.pending_queries = 0
    if on_progress is not None:
        on_progress(result)
    return result
