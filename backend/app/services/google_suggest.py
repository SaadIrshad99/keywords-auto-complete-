"""Small asynchronous client for Google's unofficial Suggest endpoint."""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable

import httpx


SUGGEST_URL = "https://suggestqueries.google.com/complete/search"


class GoogleSuggestError(Exception):
    """A Suggest request failed or returned unusable data."""


class GoogleSuggestRateLimited(GoogleSuggestError):
    """Google returned HTTP 429; callers should pause research."""


class GoogleSuggestAccessDenied(GoogleSuggestError):
    """Google returned HTTP 403; callers should stop research."""


class GoogleSuggestCancelled(GoogleSuggestError):
    """The caller requested cancellation before another HTTP attempt."""


class GoogleSuggestClient:
    """Reuse one HTTP connection pool and pace requests across this client."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        request_delay: float = 1.5,
        max_attempts: int = 3,
        retry_base_delay: float = 1.0,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        if not math.isfinite(request_delay) or request_delay < 0:
            raise ValueError("request_delay must be nonnegative")
        if not math.isfinite(retry_base_delay) or retry_base_delay < 0:
            raise ValueError("retry_base_delay must be nonnegative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self.timeout = timeout
        self.request_delay = request_delay
        self.max_attempts = max_attempts
        self.retry_base_delay = retry_base_delay
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._sleep = sleep
        self._clock = clock
        self._request_lock = asyncio.Lock()
        self._last_request_at: float | None = None

    async def __aenter__(self) -> "GoogleSuggestClient":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_suggestions(
        self,
        query: str,
        country: str = "us",
        language: str = "en",
        *,
        max_attempts: int | None = None,
        on_attempt: Callable[[bool], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> list[str]:
        """Return suggestions; optionally report each actual HTTP attempt.

        ``on_attempt`` receives True for a valid Suggest response and False for
        a failed attempt. ``max_attempts`` can cap retries to a caller's budget.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        if not country.strip() or not language.strip():
            raise ValueError("country and language must not be empty")
        attempt_limit = self.max_attempts if max_attempts is None else min(self.max_attempts, max_attempts)
        if attempt_limit < 1:
            raise ValueError("max_attempts must be at least 1")

        params = {
            "client": "firefox",
            "q": query,
            "hl": language,
            "gl": country,
        }

        for attempt in range(attempt_limit):
            if should_stop is not None and should_stop():
                raise GoogleSuggestCancelled("Suggest request cancelled")
            if attempt:
                await self._sleep(self.retry_base_delay * 2 ** (attempt - 1))
            if should_stop is not None and should_stop():
                raise GoogleSuggestCancelled("Suggest request cancelled")

            try:
                response = await self._request(params, should_stop, before_attempt)
            except httpx.RequestError as exc:
                if on_attempt is not None:
                    on_attempt(False)
                if attempt + 1 == attempt_limit:
                    raise GoogleSuggestError("Suggest request failed") from exc
                continue

            if response.status_code == 429:
                if on_attempt is not None:
                    on_attempt(False)
                # Retrying immediately after a rate limit would make it worse.
                raise GoogleSuggestRateLimited("Google Suggest returned HTTP 429")
            if response.status_code == 403:
                if on_attempt is not None:
                    on_attempt(False)
                raise GoogleSuggestAccessDenied("Google Suggest returned HTTP 403")
            if response.status_code >= 500 and attempt + 1 < attempt_limit:
                if on_attempt is not None:
                    on_attempt(False)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if on_attempt is not None:
                    on_attempt(False)
                raise GoogleSuggestError(
                    f"Google Suggest returned HTTP {response.status_code}"
                ) from exc

            try:
                payload = response.json()
            except ValueError as exc:
                if on_attempt is not None:
                    on_attempt(False)
                raise GoogleSuggestError("Google Suggest returned malformed JSON") from exc
            if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
                if on_attempt is not None:
                    on_attempt(False)
                raise GoogleSuggestError("Google Suggest returned an unexpected response")

            suggestions: list[str] = []
            seen: set[str] = set()
            for suggestion in payload[1]:
                if isinstance(suggestion, str) and suggestion.strip() and suggestion not in seen:
                    suggestions.append(suggestion)
                    seen.add(suggestion)
            if on_attempt is not None:
                on_attempt(True)
            return suggestions

        raise GoogleSuggestError("Google Suggest request failed")

    async def _request(
        self,
        params: dict[str, str],
        should_stop: Callable[[], bool] | None = None,
        before_attempt: Callable[[], Awaitable[None]] | None = None,
    ) -> httpx.Response:
        async with self._request_lock:
            if self._last_request_at is not None:
                wait = self.request_delay - (self._clock() - self._last_request_at)
                if wait > 0:
                    await self._sleep(wait)
            if before_attempt is not None:
                await before_attempt()
            if should_stop is not None and should_stop():
                raise GoogleSuggestCancelled("Suggest request cancelled")
            self._last_request_at = self._clock()
            return await self._client.get(SUGGEST_URL, params=params, timeout=self.timeout)
