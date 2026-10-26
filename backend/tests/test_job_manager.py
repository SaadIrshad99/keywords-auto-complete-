import asyncio

import httpx
import pytest

from app.research.job_manager import (
    InvalidJobTransitionError,
    JobConflictError,
    JobStatus,
    NoCurrentJobError,
    ResearchConfig,
    ResearchJobManager,
)
from app.services.google_suggest import GoogleSuggestClient


class FakeSuggestClient:
    def __init__(self, responses=None, block_query=None):
        self.responses = responses or {}
        self.block_query = block_query
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_suggestions(
        self, query, country="us", language="en", *, max_attempts=None,
        on_attempt=None, should_stop=None, before_attempt=None,
    ):
        if before_attempt is not None:
            await before_attempt()
        self.calls.append((query, country, language))
        if query == self.block_query:
            self.entered.set()
            await self.release.wait()
        response = self.responses.get(query, [])
        if isinstance(response, Exception):
            raise response
        on_attempt(True)
        return response


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=2)


def test_start_complete_progress_results_and_clear():
    async def run():
        client = FakeSuggestClient({"seed": ["seed child"]})
        manager = ResearchJobManager(lambda: client)
        started = await manager.start(ResearchConfig("seed", max_depth=1))
        assert started.status in {JobStatus.PENDING, JobStatus.RUNNING}
        assert started.job_id

        completed = await manager.wait_for_completion()
        assert completed.status is JobStatus.COMPLETED
        assert completed.started_at <= completed.ended_at
        assert completed.current_depth == 1
        assert completed.current_query is None
        assert (completed.requests_attempted, completed.requests_succeeded,
                completed.requests_failed) == (1, 1, 0)
        assert completed.unique_keywords == 1
        assert completed.pending_queries == 0
        assert completed.stop_reason == "completed"
        assert "seed child" in (await manager.get_results()).keywords

        with pytest.raises(JobConflictError):
            await manager.start(ResearchConfig("another seed"))
        results = await manager.get_results()
        await manager.clear()
        assert results.keywords == {}
        with pytest.raises(NoCurrentJobError):
            await manager.get_progress()
        await manager.start(ResearchConfig("another seed", max_depth=1))
        assert (await manager.wait_for_completion()).status is JobStatus.COMPLETED

    asyncio.run(run())


def test_pause_waits_after_in_flight_request_and_resume_continues_queue():
    async def run():
        client = FakeSuggestClient({"seed": ["seed child"]}, block_query="seed")
        manager = ResearchJobManager(lambda: client)
        await manager.start(ResearchConfig("seed", max_depth=2))
        await client.entered.wait()

        paused = await manager.pause()
        assert paused.status is JobStatus.PAUSED
        client.release.set()
        await wait_until(lambda: len((manager._job.result.keywords)) == 1)
        assert [call[0] for call in client.calls] == ["seed"]
        assert (await manager.get_progress()).pending_queries == 1

        resumed = await manager.resume()
        assert resumed.status is JobStatus.RUNNING
        finished = await manager.wait_for_completion()
        assert finished.status is JobStatus.COMPLETED
        assert [call[0] for call in client.calls] == ["seed", "seed child"]
        assert finished.requests_attempted == 2

    asyncio.run(run())


def test_cancel_during_in_flight_request_retains_partial_results():
    async def run():
        client = FakeSuggestClient({"seed": ["seed child"]}, block_query="seed")
        manager = ResearchJobManager(lambda: client)
        await manager.start(ResearchConfig("seed", max_depth=2))
        await client.entered.wait()

        cancelled = await manager.cancel()
        assert cancelled.status is JobStatus.CANCELLED
        with pytest.raises(InvalidJobTransitionError):
            await manager.clear()
        client.release.set()
        finished = await manager.wait_for_completion()
        assert finished.status is JobStatus.CANCELLED
        assert finished.stop_reason == "cancelled"
        assert finished.unique_keywords == 1
        assert finished.pending_queries == 0
        assert [call[0] for call in client.calls] == ["seed"]
        assert "seed child" in (await manager.get_results()).keywords
        await manager.clear()

    asyncio.run(run())


def test_cancel_paused_job_releases_waiter():
    async def run():
        client = FakeSuggestClient({"seed": ["seed child"]}, block_query="seed")
        manager = ResearchJobManager(lambda: client)
        await manager.start(ResearchConfig("seed", max_depth=2))
        await client.entered.wait()
        await manager.pause()
        client.release.set()
        await wait_until(lambda: len(manager._job.result.keywords) == 1)
        await manager.cancel()
        assert (await manager.wait_for_completion()).status is JobStatus.CANCELLED
        assert len(client.calls) == 1

    asyncio.run(run())


def test_background_exception_marks_job_failed():
    async def run():
        client = FakeSuggestClient({"seed": RuntimeError("unexpected failure")})
        manager = ResearchJobManager(lambda: client)
        await manager.start(ResearchConfig("seed"))
        failed = await manager.wait_for_completion()
        assert failed.status is JobStatus.FAILED
        assert failed.error_message == "unexpected failure"
        assert failed.stop_reason == "failed"
        assert failed.ended_at is not None
        await manager.clear()

    asyncio.run(run())


def test_invalid_state_transitions_and_active_clear_are_rejected():
    async def run():
        client = FakeSuggestClient(block_query="seed")
        manager = ResearchJobManager(lambda: client)
        with pytest.raises(NoCurrentJobError):
            await manager.pause()
        await manager.start(ResearchConfig("seed"))
        await client.entered.wait()
        with pytest.raises(InvalidJobTransitionError):
            await manager.resume()
        with pytest.raises(InvalidJobTransitionError):
            await manager.clear()
        await manager.pause()
        with pytest.raises(InvalidJobTransitionError):
            await manager.pause()
        await manager.cancel()
        with pytest.raises(InvalidJobTransitionError):
            await manager.resume()
        client.release.set()
        await manager.wait_for_completion()

    asyncio.run(run())


def test_live_progress_updates_before_job_finishes():
    async def run():
        client = FakeSuggestClient(
            {"seed": ["seed child"]}, block_query="seed child"
        )
        manager = ResearchJobManager(lambda: client)
        await manager.start(ResearchConfig("seed", country="de", language="de"))
        await client.entered.wait()
        progress = await manager.get_progress()
        assert progress.status is JobStatus.RUNNING
        assert progress.seed == "seed"
        assert progress.country == progress.language == "de"
        assert progress.max_depth == 2
        assert progress.current_depth == 2
        assert progress.current_query == "seed child"
        assert progress.requests_attempted == progress.requests_succeeded == 1
        assert progress.unique_keywords == 1
        client.release.set()
        await manager.wait_for_completion()

    asyncio.run(run())


def test_concurrent_start_requests_create_only_one_job():
    async def run():
        client = FakeSuggestClient(block_query="seed")
        manager = ResearchJobManager(lambda: client)
        outcomes = await asyncio.gather(
            manager.start(ResearchConfig("seed")),
            manager.start(ResearchConfig("other")),
            return_exceptions=True,
        )
        assert sum(isinstance(item, JobConflictError) for item in outcomes) == 1
        assert sum(not isinstance(item, Exception) for item in outcomes) == 1
        await client.entered.wait()
        client.release.set()
        await manager.wait_for_completion()

    asyncio.run(run())


def test_pause_during_client_pacing_blocks_next_http_request():
    async def run():
        pacing_started = asyncio.Event()
        release_pacing = asyncio.Event()
        requests = []

        async def fake_sleep(_seconds):
            pacing_started.set()
            await release_pacing.wait()

        def handler(request):
            query = request.url.params["q"]
            requests.append(query)
            suggestions = ["seed child"] if query == "seed" else []
            return httpx.Response(200, json=[query, suggestions])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            manager = ResearchJobManager(
                lambda: GoogleSuggestClient(
                    client=http_client, request_delay=1.5, sleep=fake_sleep
                )
            )
            await manager.start(ResearchConfig("seed", max_depth=2))
            await pacing_started.wait()
            await manager.pause()
            release_pacing.set()
            await asyncio.sleep(0)
            assert requests == ["seed"]
            await manager.resume()
            assert (await manager.wait_for_completion()).status is JobStatus.COMPLETED
            assert requests == ["seed", "seed child"]

    asyncio.run(run())
