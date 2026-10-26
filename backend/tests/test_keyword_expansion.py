import asyncio

import httpx
import pytest

from app.services.google_suggest import (
    GoogleSuggestClient,
    GoogleSuggestError,
    GoogleSuggestRateLimited,
)
from app.services.keyword_expansion import (
    collect_suggestions,
    generate_queries,
    keyword_key,
)


class FakeSuggestClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    async def get_suggestions(self, query, country="us", language="en"):
        self.calls.append((query, country, language))
        response = self.responses.get(query, [])
        if isinstance(response, Exception):
            raise response
        return response


def run_collection(seed, methods, client, **options):
    return asyncio.run(collect_suggestions(seed, methods, client, **options))


def test_direct_seed_is_normalized_and_only_returned_text_is_discovered():
    client = FakeSuggestClient({"age calculator": ["Age Calculator Online"]})

    result = run_collection("  age   calculator  ", ["direct"], client)

    assert client.calls == [("age calculator", "us", "en")]
    assert result.queries_generated == 1
    assert result.requests_attempted == result.requests_succeeded == 1
    assert result.requests_failed == 0
    assert result.unique_keywords_discovered == 1
    assert result.keywords[keyword_key("Age Calculator Online")].text == "Age Calculator Online"
    assert "age calculator" not in result.keywords


def test_alphabet_prefix_and_suffix_have_canonical_order():
    queries = list(generate_queries(" age   calculator ", ["alphabet_prefix", "alphabet_suffix"]))

    assert len(queries) == 52
    assert [query.text for query in queries[:3]] == [
        "age calculator a", "age calculator b", "age calculator c"
    ]
    assert queries[25].text == "age calculator z"
    assert queries[26].text == "a age calculator"
    assert queries[-1].text == "z age calculator"


def test_numeric_prefix_and_suffix_have_canonical_order():
    queries = list(generate_queries("age calculator", ["numeric_prefix", "numeric_suffix"]))

    assert [query.text for query in queries] == [
        *(f"age calculator {digit}" for digit in "0123456789"),
        *(f"{digit} age calculator" for digit in "0123456789"),
    ]


def test_custom_modifiers_are_suffixes_and_duplicate_queries_are_skipped():
    queries = list(
        generate_queries(
            "age calculator",
            ["modifier_suffix", "direct", "modifier_suffix"],
            ["  online ", "online", "FREE", "free", ""],
        )
    )

    assert [(item.text, item.method) for item in queries] == [
        ("age calculator", "direct"),
        ("age calculator online", "modifier_suffix"),
        ("age calculator FREE", "modifier_suffix"),
    ]


def test_duplicate_keywords_keep_first_text_and_multiple_discovery_paths():
    client = FakeSuggestClient(
        {
            "age calculator": ["Age Calculator Online", "age calculator online"],
            "age calculator a": ["AGE CALCULATOR ONLINE", "Age Calculator App"],
        }
    )

    result = run_collection("age calculator", ["direct", "alphabet_suffix"], client, max_requests=2)

    assert result.unique_keywords_discovered == 2
    keyword = result.keywords[keyword_key("age calculator online")]
    assert keyword.text == "Age Calculator Online"
    assert keyword.first_discovery_query == "age calculator"
    assert keyword.expansion_method == "direct"
    assert [(item.query, item.method) for item in keyword.discoveries] == [
        ("age calculator", "direct"),
        ("age calculator a", "alphabet_suffix"),
    ]


def test_request_budget_stops_before_generating_more_queries():
    client = FakeSuggestClient()

    result = run_collection("age calculator", ["direct", "alphabet_suffix"], client, max_requests=3)

    assert [call[0] for call in client.calls] == [
        "age calculator", "age calculator a", "age calculator b"
    ]
    assert result.queries_generated == result.requests_attempted == 3
    assert result.requests_succeeded == 3


def test_country_and_language_are_forwarded_for_every_request():
    client = FakeSuggestClient()

    run_collection(
        "altersrechner", ["direct", "numeric_prefix"], client,
        country="de", language="de", max_requests=2,
    )

    assert client.calls == [
        ("altersrechner", "de", "de"),
        ("0 altersrechner", "de", "de"),
    ]


def test_empty_results_and_failed_request_update_counters():
    client = FakeSuggestClient({"age calculator": GoogleSuggestError("timeout")})

    result = run_collection("age calculator", ["direct", "numeric_suffix"], client, max_requests=2)

    assert result.requests_attempted == 2
    assert result.requests_succeeded == 1
    assert result.requests_failed == 1
    assert result.unique_keywords_discovered == 0
    assert result.failures[0].query == "age calculator"


def test_rate_limit_stops_expansion_immediately():
    client = FakeSuggestClient({"age calculator": GoogleSuggestRateLimited("HTTP 429")})

    result = run_collection("age calculator", ["direct", "alphabet_suffix"], client)

    assert len(client.calls) == 1
    assert result.requests_attempted == result.requests_failed == 1
    assert result.requests_succeeded == 0


@pytest.mark.parametrize(
    ("seed", "methods", "budget"),
    [(" ", ["direct"], 1), ("age calculator", [], 1), ("age calculator", ["unknown"], 1),
     ("age calculator", ["direct"], 0)],
)
def test_invalid_input_is_rejected(seed, methods, budget):
    with pytest.raises(ValueError):
        run_collection(seed, methods, FakeSuggestClient(), max_requests=budget)


def test_result_can_release_collected_data():
    client = FakeSuggestClient({"age calculator": ["Age Calculator Online"]})
    result = run_collection("age calculator", ["direct"], client)

    result.clear()

    assert result.keywords == {}
    assert result.failures == []


def test_one_pass_uses_existing_httpx_suggest_client_with_mocked_response():
    async def run():
        def handler(request):
            assert request.url.params["q"] == "age calculator"
            return httpx.Response(200, json=["age calculator", ["Age Calculator Online"]])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(client=http_client, request_delay=0) as client:
                return await collect_suggestions("age calculator", ["direct"], client)

    result = asyncio.run(run())
    assert result.unique_keywords_discovered == 1
    assert result.requests_succeeded == 1
