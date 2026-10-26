import asyncio

import httpx
import pytest

from app.services.google_suggest import (
    GoogleSuggestClient,
    GoogleSuggestError,
    GoogleSuggestRateLimited,
)
from app.services.recursive_research import research_keywords


class FakeSuggestClient:
    def __init__(self, responses=None, cancel_event=None):
        self.responses = responses or {}
        self.cancel_event = cancel_event
        self.calls = []

    async def get_suggestions(
        self, query, country="us", language="en", *, max_attempts=None,
        on_attempt=None, should_stop=None,
    ):
        assert max_attempts >= 1
        self.calls.append((query, country, language))
        response = self.responses.get(query, [])
        on_attempt(not isinstance(response, Exception))
        if self.cancel_event is not None:
            self.cancel_event.set()
        if isinstance(response, Exception):
            raise response
        return response


def run_research(seed, client, **options):
    return asyncio.run(research_keywords(seed, ["direct"], client, **options))


@pytest.mark.parametrize("max_depth", [1, 2, 3, 4])
def test_depth_semantics_and_no_expansion_past_limit(max_depth):
    responses = {
        "seed": ["seed one"],
        "seed one": ["seed two"],
        "seed two": ["seed three"],
        "seed three": ["seed four"],
    }
    client = FakeSuggestClient(responses)

    result = run_research("seed", client, max_depth=max_depth)

    assert [call[0] for call in client.calls] == list(responses)[:max_depth]
    assert result.keywords[f"seed {['one', 'two', 'three', 'four'][max_depth - 1]}"].first_depth == max_depth
    assert result.requests_attempted == max_depth


def test_bfs_processes_all_lower_depth_queries_first():
    client = FakeSuggestClient({
        "seed": ["seed a", "seed b"],
        "seed a": ["seed a child"],
        "seed b": ["seed b child"],
    })

    result = run_research("seed", client, max_depth=3)

    assert [call[0] for call in client.calls] == [
        "seed", "seed a", "seed b", "seed a child", "seed b child"
    ]
    assert result.stop_reason == "completed"


def test_duplicate_keyword_keeps_multiple_parents_but_expands_once():
    client = FakeSuggestClient({
        "seed": ["seed a", "seed b", "SEED A"],
        "seed a": ["seed shared"],
        "seed b": ["SEED SHARED"],
        "seed shared": ["seed leaf"],
    })

    result = run_research("seed", client, max_depth=3)

    assert [call[0] for call in client.calls].count("seed shared") == 1
    assert [call[0] for call in client.calls].count("seed a") == 1
    shared = result.keywords["seed shared"]
    assert shared.text == "seed shared"
    assert shared.first_depth == 2
    assert [(item.parent_keyword, item.query, item.depth) for item in shared.discoveries] == [
        ("seed a", "seed a", 2), ("seed b", "seed b", 2)
    ]


def test_selected_expansions_are_used_at_each_depth_in_deterministic_order():
    client = FakeSuggestClient({"seed": ["seed child"]})

    result = asyncio.run(research_keywords(
        "seed", ["numeric_suffix", "direct"], client,
        max_depth=2, max_requests=3,
    ))

    assert [call[0] for call in client.calls] == ["seed", "seed 0", "seed 1"]
    assert result.stop_reason == "max_requests"


def test_relevance_filters_expansion_but_keeps_returned_suggestions():
    client = FakeSuggestClient({"age calculator": ["age calculator online", "unrelated tool"]})

    result = run_research("age calculator", client, max_depth=2)

    assert [call[0] for call in client.calls] == ["age calculator", "age calculator online"]
    assert "unrelated tool" in result.keywords
    assert "unrelated tool" not in result.expanded_keywords


def test_seed_terms_option_allows_reordered_terms():
    client = FakeSuggestClient({"age calculator": ["calculator age online"]})

    result = run_research("age calculator", client, relevance="seed_terms", max_depth=2)

    assert [call[0] for call in client.calls] == ["age calculator", "calculator age online"]
    assert result.keywords["calculator age online"].first_depth == 1


def test_request_budget_counts_http_retries_and_stops_before_next_query():
    attempts = []

    async def run():
        def handler(request):
            attempts.append(request.url.params["q"])
            if len(attempts) == 1:
                return httpx.Response(503)
            return httpx.Response(200, json=["seed", ["seed child"]])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(
                client=http_client, request_delay=0, retry_base_delay=0
            ) as client:
                return await research_keywords("seed", ["direct"], client, max_requests=2)

    result = asyncio.run(run())
    assert attempts == ["seed", "seed"]
    assert result.requests_attempted == 2
    assert result.requests_succeeded == 1
    assert result.requests_failed == 1
    assert result.stop_reason == "max_requests"


def test_budget_caps_client_retries_to_remaining_attempts():
    attempts = 0

    async def run():
        def handler(request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(
                client=http_client, request_delay=0, retry_base_delay=0
            ) as client:
                return await research_keywords("seed", ["direct"], client, max_requests=1)

    result = asyncio.run(run())
    assert attempts == 1
    assert result.requests_attempted == result.requests_failed == 1
    assert result.requests_succeeded == 0


def test_maximum_keyword_limit_stops_safely():
    client = FakeSuggestClient({"seed": ["seed one", "seed two", "seed three"]})

    result = run_research("seed", client, max_keywords=2)

    assert result.unique_keywords_discovered == 2
    assert result.stop_reason == "max_keywords"
    assert [call[0] for call in client.calls] == ["seed"]


def test_pending_queue_limit_truncates_without_exceeding_capacity():
    client = FakeSuggestClient()

    result = asyncio.run(research_keywords(
        "seed", ["direct", "alphabet_suffix"], client,
        max_pending_queue=2, max_depth=1,
    ))

    assert [call[0] for call in client.calls] == ["seed", "seed a"]
    assert result.queue_truncated is True
    assert result.stop_reason == "completed"


def test_cancellation_stops_between_requests():
    event = asyncio.Event()
    client = FakeSuggestClient({"seed": ["seed child"]}, cancel_event=event)

    result = run_research("seed", client, cancel_event=event)

    assert [call[0] for call in client.calls] == ["seed"]
    assert result.stop_reason == "cancelled"


def test_cancellation_between_retries_prevents_another_http_attempt():
    event = asyncio.Event()
    attempts = 0

    async def run():
        def handler(request):
            nonlocal attempts
            attempts += 1
            event.set()
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(
                client=http_client, request_delay=0, retry_base_delay=0
            ) as client:
                return await research_keywords(
                    "seed", ["direct"], client, cancel_event=event
                )

    result = asyncio.run(run())
    assert attempts == 1
    assert result.requests_attempted == result.requests_failed == 1
    assert result.stop_reason == "cancelled"


def test_rate_limit_stops_research_without_scheduling_more_requests():
    client = FakeSuggestClient({"seed": GoogleSuggestRateLimited("HTTP 429")})

    result = asyncio.run(research_keywords(
        "seed", ["direct", "alphabet_suffix"], client
    ))

    assert [call[0] for call in client.calls] == ["seed"]
    assert result.stop_reason == "rate_limited"
    assert result.requests_failed == 1


def test_empty_suggestions_and_api_failures_are_counted():
    client = FakeSuggestClient({"seed": GoogleSuggestError("timeout")})

    result = run_research("seed", client)

    assert result.requests_attempted == result.requests_failed == 1
    assert result.requests_succeeded == 0
    assert result.failures == ["seed: timeout"]
    assert result.stop_reason == "completed"


def test_country_and_language_propagate_at_every_depth():
    client = FakeSuggestClient({"seed": ["seed child"]})

    run_research("seed", client, country="br", language="pt", max_depth=2)

    assert client.calls == [("seed", "br", "pt"), ("seed child", "br", "pt")]


@pytest.mark.parametrize("depth", [0, 5, True])
def test_invalid_depth_is_rejected(depth):
    with pytest.raises(ValueError, match="max_depth"):
        run_research("seed", FakeSuggestClient(), max_depth=depth)
