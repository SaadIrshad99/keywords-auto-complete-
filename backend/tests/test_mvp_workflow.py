"""A local API-to-worker workflow with deterministic Suggest responses."""

import asyncio
import csv
from io import StringIO

import httpx

from app.main import create_app
from app.research.job_manager import ResearchJobManager
from app.services.recursive_research import research_keywords


class ControlledSuggest:
    def __init__(self):
        self.second_request = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def get_suggestions(self, query, *, country, language, on_attempt, **_options):
        self.calls.append((query, country, language))
        if query != "age calculator":
            self.second_request.set()
            await self.release.wait()
        on_attempt(True)
        return {
            "age calculator": ["age calculator online", "Kalkülator, Größe", "حاسبة العمر", "calculadora grátis"],
            "age calculator online": ["age calculator online free", "Kalkülator, Größe"],
        }.get(query, [])


def test_full_control_export_clear_restart_and_new_session():
    async def scenario():
        fake = ControlledSuggest()
        app = create_app(ResearchJobManager(lambda: fake))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            settings = {"seed": "age calculator", "country": "de", "language": "en",
                        "max_depth": 2, "max_requests": 5, "methods": ["direct"], "relevance": "none"}
            first = await client.post("/api/research", json=settings)
            assert first.status_code == 201
            assert (await client.post("/api/research", json=settings)).status_code == 409
            await asyncio.wait_for(fake.second_request.wait(), 1)
            progress = (await client.get("/api/research/current")).json()
            assert progress["requests_attempted"] == 1
            assert progress["unique_keywords"] == 4
            assert progress["country"] == "de" and progress["language"] == "en"
            assert (await client.delete("/api/research/current")).status_code == 409
            assert (await client.post("/api/research/current/pause")).json()["status"] == "PAUSED"
            filtered = (await client.get("/api/research/current/keywords?filter=calculator&limit=1")).json()
            assert filtered["total"] == 1 and len(filtered["items"]) == 1
            assert (await client.post("/api/research/current/resume")).json()["status"] == "RUNNING"
            partial = await client.get("/api/research/current/export")
            assert partial.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(StringIO(partial.content.decode("utf-8-sig"))))
            assert [row[0] for row in rows[1:]] == [
                "age calculator online", "Kalkülator, Größe", "حاسبة العمر", "calculadora grátis"
            ]
            assert (await client.get("/api/research/current")).json()["unique_keywords"] == 4
            assert (await client.post("/api/research/current/cancel")).json()["status"] == "CANCELLED"
            assert (await client.delete("/api/research/current")).status_code == 409
            fake.release.set()
            await app.state.research_manager.wait_for_completion()
            # The in-flight request may finish and add one keyword after cancel.
            assert (await client.get("/api/research/current/keywords")).json()["total"] == 5
            assert len(fake.calls) == 2
            assert (await client.delete("/api/research/current")).status_code == 204
            assert (await client.get("/api/research/current")).status_code == 404

            next_job = await client.post("/api/research", json={"seed": "fresh seed", "max_depth": 1})
            assert next_job.status_code == 201
            await app.state.research_manager.wait_for_completion()
            assert (await client.get("/api/research/current/keywords")).json()["total"] == 0
            assert (await client.get("/api/research/current/export")).content.startswith(b"\xef\xbb\xbf")

        # A new process would construct a new app and manager with no retained job.
        restarted = create_app(ResearchJobManager(lambda: ControlledSuggest()))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://local") as client:
            assert (await client.get("/api/research/current")).status_code == 404
            assert (await client.get("/api/research/current/keywords")).status_code == 404
    asyncio.run(scenario())


def test_dense_graph_stays_within_all_safety_limits():
    class DenseSuggest:
        def __init__(self):
            self.calls = []

        async def get_suggestions(self, query, *, on_attempt, **_kwargs):
            self.calls.append(query)
            on_attempt(True)
            return [f"seed {query} child {index}" for index in range(100)]

    async def scenario():
        client = DenseSuggest()
        result = await research_keywords(
            "seed", ["direct"], client, max_depth=4, max_requests=7,
            max_keywords=50, max_pending_queue=10, relevance="none",
        )
        assert len(client.calls) <= 7
        assert result.requests_attempted <= 7
        assert result.unique_keywords_discovered <= 50
        assert result.pending_queries <= 10
        assert result.stop_reason in {"max_keywords", "max_requests"}
        assert result.queue_truncated or result.stop_reason == "max_keywords"
    asyncio.run(scenario())
