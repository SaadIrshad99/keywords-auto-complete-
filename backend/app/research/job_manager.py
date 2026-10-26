"""Single-job, in-memory lifecycle around the recursive research engine."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import AsyncContextManager
from uuid import uuid4

from app.services.google_suggest import GoogleSuggestClient
from app.services.recursive_research import ResearchResult, research_keywords


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class JobConflictError(Exception):
    """The existing job must be finished and cleared before starting another."""


class InvalidJobTransitionError(Exception):
    """The requested operation is not valid for the current job state."""


class NoCurrentJobError(Exception):
    """There is no in-memory research job to inspect or control."""


@dataclass(frozen=True)
class ResearchConfig:
    seed: str
    methods: tuple[str, ...] = ("direct",)
    country: str = "us"
    language: str = "en"
    modifiers: tuple[str, ...] = ()
    max_depth: int = 2
    max_requests: int = 500
    max_keywords: int = 10000
    max_pending_queue: int = 1000
    relevance: str = "seed_phrase"
    request_delay: float = 1.5


@dataclass(frozen=True)
class JobProgress:
    job_id: str
    seed: str
    country: str
    language: str
    status: JobStatus
    max_depth: int
    max_requests: int
    max_keywords: int
    max_pending_queue: int
    request_delay: float
    methods: tuple[str, ...]
    modifiers: tuple[str, ...]
    relevance: str
    current_depth: int
    current_query: str | None
    requests_attempted: int
    requests_succeeded: int
    requests_failed: int
    unique_keywords: int
    pending_queries: int
    started_at: datetime
    ended_at: datetime | None
    error_message: str | None
    stop_reason: str | None
    queue_truncated: bool


@dataclass
class _Job:
    id: str
    config: ResearchConfig
    started_at: datetime
    status: JobStatus = JobStatus.PENDING
    ended_at: datetime | None = None
    error_message: str | None = None
    result: ResearchResult = field(default_factory=ResearchResult)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


class ResearchJobManager:
    """Own at most one active or retained finished job in one event loop."""

    def __init__(
        self,
        client_factory: Callable[[], AsyncContextManager[GoogleSuggestClient]] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._lock = asyncio.Lock()
        self._job: _Job | None = None

    async def start(self, config: ResearchConfig) -> JobProgress:
        async with self._lock:
            if self._job is not None:
                raise JobConflictError("clear the current job before starting another")
            job = _Job(str(uuid4()), config, datetime.now(timezone.utc))
            job.resume_event.set()
            self._job = job
            job.task = asyncio.create_task(self._run(job))
            return self._snapshot(job)

    async def pause(self) -> JobProgress:
        async with self._lock:
            job = self._require_job()
            if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
                raise InvalidJobTransitionError(f"cannot pause a {job.status} job")
            job.resume_event.clear()
            job.status = JobStatus.PAUSED
            return self._snapshot(job)

    async def resume(self) -> JobProgress:
        async with self._lock:
            job = self._require_job()
            if job.status is not JobStatus.PAUSED:
                raise InvalidJobTransitionError(f"cannot resume a {job.status} job")
            job.status = JobStatus.RUNNING
            job.resume_event.set()
            return self._snapshot(job)

    async def cancel(self) -> JobProgress:
        async with self._lock:
            job = self._require_job()
            if job.status not in {JobStatus.PENDING, JobStatus.RUNNING, JobStatus.PAUSED}:
                raise InvalidJobTransitionError(f"cannot cancel a {job.status} job")
            job.status = JobStatus.CANCELLED
            job.cancel_event.set()
            job.resume_event.set()  # Release a paused task so it can exit.
            return self._snapshot(job)

    async def get_progress(self) -> JobProgress:
        async with self._lock:
            return self._snapshot(self._require_job())

    async def get_results(self) -> ResearchResult:
        """Return the live result object without copying a large keyword collection."""
        async with self._lock:
            return self._require_job().result

    async def clear(self) -> None:
        async with self._lock:
            job = self._require_job()
            if job.status not in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}:
                raise InvalidJobTransitionError("cannot clear an active job")
            if job.task is not None and not job.task.done():
                raise InvalidJobTransitionError("wait for the job to stop before clearing it")
            job.result.clear()
            job.task = None
            self._job = None

    async def wait_for_completion(self) -> JobProgress:
        """Wait for the current task; useful for local callers and tests."""
        async with self._lock:
            job = self._require_job()
            task = job.task
        if task is not None:
            await task
        return await self.get_progress()

    async def _run(self, job: _Job) -> None:
        try:
            async with self._lock:
                if job.status is JobStatus.CANCELLED:
                    job.result.stop_reason = "cancelled"
                    job.ended_at = datetime.now(timezone.utc)
                    return
                if job.status is JobStatus.PENDING:
                    job.status = JobStatus.RUNNING

            config = job.config
            client_context = (
                self._client_factory()
                if self._client_factory is not None
                else GoogleSuggestClient(request_delay=config.request_delay)
            )
            async with client_context as client:
                await research_keywords(
                    config.seed,
                    config.methods,
                    client,
                    country=config.country,
                    language=config.language,
                    modifiers=config.modifiers,
                    max_depth=config.max_depth,
                    max_requests=config.max_requests,
                    max_keywords=config.max_keywords,
                    max_pending_queue=config.max_pending_queue,
                    relevance=config.relevance,
                    cancel_event=job.cancel_event,
                    pause_event=job.resume_event,
                    result=job.result,
                )

            async with self._lock:
                if job.status is JobStatus.CANCELLED or job.result.stop_reason == "cancelled":
                    job.status = JobStatus.CANCELLED
                    job.result.stop_reason = "cancelled"
                elif job.result.stop_reason in {"rate_limited", "access_denied"}:
                    job.status = JobStatus.FAILED
                    job.error_message = job.result.failures[-1] if job.result.failures else job.result.stop_reason
                else:
                    job.status = JobStatus.COMPLETED
                job.ended_at = datetime.now(timezone.utc)
        except asyncio.CancelledError:
            async with self._lock:
                job.status = JobStatus.CANCELLED
                job.result.stop_reason = "cancelled"
                job.ended_at = datetime.now(timezone.utc)
            raise
        except Exception as exc:
            async with self._lock:
                job.status = JobStatus.FAILED
                job.result.stop_reason = "failed"
                job.error_message = str(exc)
                job.ended_at = datetime.now(timezone.utc)

    def _require_job(self) -> _Job:
        if self._job is None:
            raise NoCurrentJobError("no current research job")
        return self._job

    @staticmethod
    def _snapshot(job: _Job) -> JobProgress:
        result = job.result
        return JobProgress(
            job_id=job.id,
            seed=job.config.seed,
            country=job.config.country,
            language=job.config.language,
            status=job.status,
            max_depth=job.config.max_depth,
            max_requests=job.config.max_requests,
            max_keywords=job.config.max_keywords,
            max_pending_queue=job.config.max_pending_queue,
            request_delay=job.config.request_delay,
            methods=job.config.methods,
            modifiers=job.config.modifiers,
            relevance=job.config.relevance,
            current_depth=result.current_depth,
            current_query=result.current_query,
            requests_attempted=result.requests_attempted,
            requests_succeeded=result.requests_succeeded,
            requests_failed=result.requests_failed,
            unique_keywords=result.unique_keywords_discovered,
            pending_queries=result.pending_queries,
            started_at=job.started_at,
            ended_at=job.ended_at,
            error_message=job.error_message,
            stop_reason=result.stop_reason if job.ended_at is not None else None,
            queue_truncated=result.queue_truncated,
        )
