import asyncio
import json

import httpx
import pytest

from app.services.google_suggest import (
    GoogleSuggestAccessDenied,
    GoogleSuggestCancelled,
    GoogleSuggestClient,
    GoogleSuggestError,
    GoogleSuggestRateLimited,
)


def run_request(handler, **client_options):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            options = {"request_delay": 0, "retry_base_delay": 0, **client_options}
            async with GoogleSuggestClient(
                client=http_client, **options
            ) as suggest_client:
                return await suggest_client.get_suggestions("age calculator")

    return asyncio.run(run())


def test_returns_original_suggestions_in_order_without_empty_or_duplicate_items():
    def handler(request):
        return httpx.Response(
            200,
            json=["age calculator", ["Age Calculator", "", "  ", "age calculator online", "Age Calculator", 42]],
        )

    assert run_request(handler) == ["Age Calculator", "age calculator online"]


def test_empty_suggestion_list():
    assert run_request(lambda request: httpx.Response(200, json=["age calculator", []])) == []


@pytest.mark.parametrize(
    ("country", "language"),
    [("us", "en"), ("gb", "en"), ("de", "de"), ("br", "pt"), ("sa", "ar")],
)
def test_sends_independent_country_and_language_parameters(country, language):
    async def run():
        def handler(request):
            assert request.url.params["client"] == "firefox"
            assert request.url.params["q"] == "cálculo عمر"
            assert request.url.params["gl"] == country
            assert request.url.params["hl"] == language
            assert request.url.path == "/complete/search"
            return httpx.Response(200, json=["cálculo عمر", []])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(client=http_client, request_delay=0) as client:
                return await client.get_suggestions("cálculo عمر", country, language)

    assert asyncio.run(run()) == []


@pytest.mark.parametrize("status", [400, 500])
def test_non_success_status_raises_after_bounded_attempts(status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    with pytest.raises(GoogleSuggestError, match=f"HTTP {status}"):
        run_request(handler)
    assert calls == (3 if status == 500 else 1)


def test_timeout_retries_then_raises():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(GoogleSuggestError, match="request failed"):
        run_request(handler)
    assert calls == 3


def test_connection_error_retries_then_raises():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(GoogleSuggestError, match="request failed"):
        run_request(handler)
    assert calls == 3


def test_malformed_json_raises_without_retry():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"not json")

    with pytest.raises(GoogleSuggestError, match="malformed JSON"):
        run_request(handler)
    assert calls == 1


@pytest.mark.parametrize("payload", [{"suggestions": []}, ["query"], ["query", "bad"]])
def test_unexpected_structure_raises(payload):
    with pytest.raises(GoogleSuggestError, match="unexpected response"):
        run_request(lambda request: httpx.Response(200, content=json.dumps(payload)))


def test_transient_error_retries_with_exponential_backoff():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=["query", ["result"]])

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    assert run_request(handler, sleep=fake_sleep, retry_base_delay=1) == ["result"]
    assert calls == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(429, GoogleSuggestRateLimited), (403, GoogleSuggestAccessDenied)],
)
def test_access_restrictions_stop_without_retry(status, error_type):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    with pytest.raises(error_type):
        run_request(handler)
    assert calls == 1


def test_request_delay_spaces_successive_calls():
    now = 0.0
    request_times = []

    def clock():
        return now

    async def fake_sleep(seconds):
        nonlocal now
        now += seconds

    def handler(request):
        request_times.append(now)
        return httpx.Response(200, json=["query", []])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(
                client=http_client, request_delay=1.5, sleep=fake_sleep, clock=clock
            ) as client:
                await client.get_suggestions("first")
                await client.get_suggestions("second")

    asyncio.run(run())
    assert request_times == [0.0, 1.5]


def test_attempt_callback_counts_retry_and_success():
    calls = 0
    outcomes = []

    async def run():
        def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(503) if calls == 1 else httpx.Response(200, json=["q", []])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(
                client=http_client, request_delay=0, retry_base_delay=0
            ) as client:
                return await client.get_suggestions("q", on_attempt=outcomes.append)

    assert asyncio.run(run()) == []
    assert outcomes == [False, True]


def test_attempt_limit_prevents_retry_beyond_remaining_budget():
    outcomes = []

    with pytest.raises(GoogleSuggestError, match="HTTP 503"):
        async def run():
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(503))
            ) as http_client:
                async with GoogleSuggestClient(client=http_client, request_delay=0) as client:
                    await client.get_suggestions("q", max_attempts=1, on_attempt=outcomes.append)

        asyncio.run(run())

    assert outcomes == [False]


def test_cancellation_before_request_makes_no_http_attempt():
    outcomes = []
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=["q", []])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            async with GoogleSuggestClient(client=http_client, request_delay=0) as client:
                await client.get_suggestions(
                    "q", on_attempt=outcomes.append, should_stop=lambda: True
                )

    with pytest.raises(GoogleSuggestCancelled):
        asyncio.run(run())
    assert calls == 0
    assert outcomes == []
