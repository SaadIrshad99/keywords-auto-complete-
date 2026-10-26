"""API tests use an in-memory Suggest double; no live Google requests."""

import asyncio
import csv
from io import StringIO

import httpx
import pytest

from app.main import create_app
from app.research.job_manager import ResearchJobManager


class FakeSuggest:
    def __init__(self, replies=None, gate=None):
        self.replies = replies or {}
        self.gate = gate
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def get_suggestions(self, query, *, on_attempt=None, **_kwargs):
        self.calls += 1
        if self.gate is not None and self.calls > 1:
            await self.gate.wait()
        if on_attempt is not None:
            on_attempt(True)
        return self.replies.get(query, [])


def api(fake):
    manager = ResearchJobManager(lambda: fake)
    app = create_app(manager)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test"), manager


async def wait_for_status(client, expected):
    for _ in range(100):
        response = await client.get("/api/research/current")
        if response.json()["status"] == expected:
            return response.json()
        await asyncio.sleep(0)
    pytest.fail(f"job did not reach {expected}")


def test_start_poll_results_export_clear_and_validation():
    async def scenario():
        fake = FakeSuggest({"age calculator": ["Age, calculator", "=SUM(1,2)", " age calculator free"]})
        client, manager = api(fake)
        async with client:
            assert (await client.post("/api/research", json={"seed": "  "})).status_code == 422
            assert (await client.post("/api/research", json={"seed": "x", "max_depth": 5})).status_code == 422
            assert (await client.post("/api/research", json={"seed": "x", "methods": []})).status_code == 422
            assert (await client.post("/api/research", json={"seed": "x", "methods": ["modifier_suffix"]})).status_code == 422
            response = await client.post("/api/research", json={"seed": " age   calculator ", "max_depth": 1})
            assert response.status_code == 201
            assert response.json()["seed"] == "age calculator"
            assert response.json()["max_requests"] == 500
            assert (await client.post("/api/research", json={"seed": "another"})).status_code == 409
            final = await wait_for_status(client, "COMPLETED")
            assert final["unique_keywords"] == 3
            assert final["requests_succeeded"] == 1
            assert final["ended_at"] is not None
            assert (await client.post("/api/research/current/resume")).status_code == 409

            page = (await client.get("/api/research/current/keywords?offset=1&limit=1")).json()
            assert page["total"] == 3
            assert len(page["items"]) == 1
            assert page["items"][0]["keyword"] == "=SUM(1,2)"
            assert page["items"][0]["first_discovery_query"] == "age calculator"
            assert (await client.get("/api/research/current/keywords?filter=CALCULATOR")).json()["total"] == 2
            assert (await client.get("/api/research/current/keywords?limit=201")).status_code == 422

            export = await client.get("/api/research/current/export")
            assert export.status_code == 200
            assert export.content.startswith(b"\xef\xbb\xbf")
            rows = list(csv.reader(StringIO(export.content.decode("utf-8-sig"))))
            assert rows[0] == ["Keyword", "Depth", "First Discovery Query", "Expansion Method", "Discovery Queries"]
            assert rows[1][0] == "Age, calculator"
            assert rows[2][0] == "'=SUM(1,2)"
            assert len(rows) == 4
            assert (await client.delete("/api/research/current")).status_code == 204
            assert (await client.get("/api/research/current")).status_code == 404
            assert (await client.post("/api/research", json={"seed": "next"})).status_code == 201
            await manager.wait_for_completion()
    asyncio.run(scenario())


def test_pause_resume_cancel_and_partial_export():
    async def scenario():
        gate = asyncio.Event()
        fake = FakeSuggest({"seed": ["seed next", "+formula"]}, gate)
        client, manager = api(fake)
        async with client:
            response = await client.post("/api/research", json={
                "seed": "seed", "max_depth": 2, "methods": ["direct"], "relevance": "none"
            })
            assert response.status_code == 201
            for _ in range(100):
                if fake.calls > 1:
                    break
                await asyncio.sleep(0)
            assert fake.calls == 2
            assert (await client.post("/api/research/current/pause")).json()["status"] == "PAUSED"
            assert (await client.delete("/api/research/current")).status_code == 409
            assert (await client.post("/api/research/current/pause")).status_code == 409
            partial = await client.get("/api/research/current/export")
            rows = list(csv.reader(StringIO(partial.content.decode("utf-8-sig"))))
            assert len(rows) == 3
            assert rows[2][0] == "'+formula"
            assert (await client.post("/api/research/current/resume")).json()["status"] == "RUNNING"
            assert (await client.post("/api/research/current/cancel")).json()["status"] == "CANCELLED"
            gate.set()
            await manager.wait_for_completion()
            assert (await client.get("/api/research/current")).json()["stop_reason"] == "cancelled"
            assert (await client.get("/api/research/current/keywords")).json()["total"] == 2
            assert (await client.delete("/api/research/current")).status_code == 204
    asyncio.run(scenario())


def test_missing_job_and_concurrent_start():
    async def scenario():
        client, manager = api(FakeSuggest())
        async with client:
            for method, path in [
                ("get", "/api/research/current"),
                ("get", "/api/research/current/keywords"),
                ("get", "/api/research/current/export"),
                ("post", "/api/research/current/pause"),
                ("post", "/api/research/current/resume"),
                ("post", "/api/research/current/cancel"),
                ("delete", "/api/research/current"),
            ]:
                assert (await client.request(method, path)).status_code == 404
            responses = await asyncio.gather(*[
                client.post("/api/research", json={"seed": "seed"}) for _ in range(2)
            ])
            assert sorted(response.status_code for response in responses) == [201, 409]
            await manager.wait_for_completion()
    asyncio.run(scenario())


def test_csv_formula_guard_for_untrusted_metadata():
    async def scenario():
        fake = FakeSuggest({"@seed": ["\t=SUM(1,2)", "-danger"]})
        client, manager = api(fake)
        async with client:
            assert (await client.post("/api/research", json={"seed": "@seed", "max_depth": 1})).status_code == 201
            await manager.wait_for_completion()
            response = await client.get("/api/research/current/export")
            rows = list(csv.reader(StringIO(response.content.decode("utf-8-sig"))))
            assert rows[1][0] == "'\t=SUM(1,2)"
            assert rows[1][2] == "'@seed"
            assert rows[2][0] == "'-danger"
    asyncio.run(scenario())


def test_failed_job_keeps_partial_results_for_export():
    class FailingSuggest(FakeSuggest):
        async def get_suggestions(self, query, **kwargs):
            if query != "seed":
                raise RuntimeError("mock worker failure")
            return await super().get_suggestions(query, **kwargs)

    async def scenario():
        client, manager = api(FailingSuggest({"seed": ["seed next"]}))
        async with client:
            response = await client.post("/api/research", json={"seed": "seed", "max_depth": 2})
            assert response.status_code == 201
            final = await manager.wait_for_completion()
            assert final.status == "FAILED"
            progress = (await client.get("/api/research/current")).json()
            assert progress["error_message"] == "mock worker failure"
            assert progress["unique_keywords"] == 1
            rows = list(csv.reader(StringIO((await client.get("/api/research/current/export")).content.decode("utf-8-sig"))))
            assert len(rows) == 2
            assert (await client.delete("/api/research/current")).status_code == 204
    asyncio.run(scenario())
