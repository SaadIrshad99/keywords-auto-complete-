"""One-pass query expansion and in-memory Suggest result collection."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from app.services.google_suggest import (
    GoogleSuggestAccessDenied,
    GoogleSuggestClient,
    GoogleSuggestError,
    GoogleSuggestRateLimited,
)


METHOD_ORDER = (
    "direct",
    "alphabet_suffix",
    "alphabet_prefix",
    "numeric_suffix",
    "numeric_prefix",
    "modifier_suffix",
)


def normalize_whitespace(text: str) -> str:
    """Collapse whitespace without changing the visible characters or case."""
    return " ".join(text.split())


def keyword_key(text: str) -> str:
    """Use a Unicode-aware case-insensitive key for in-memory deduplication."""
    return normalize_whitespace(text).casefold()


@dataclass(frozen=True)
class ExpansionQuery:
    text: str
    method: str


@dataclass(frozen=True)
class Discovery:
    query: str
    method: str


@dataclass
class DiscoveredKeyword:
    text: str
    first_discovery_query: str
    expansion_method: str
    discoveries: list[Discovery] = field(default_factory=list)


@dataclass(frozen=True)
class QueryFailure:
    query: str
    method: str
    error: str


@dataclass
class ExpansionResult:
    queries_generated: int = 0
    requests_attempted: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    keywords: dict[str, DiscoveredKeyword] = field(default_factory=dict)
    failures: list[QueryFailure] = field(default_factory=list)

    @property
    def unique_keywords_discovered(self) -> int:
        return len(self.keywords)

    def clear(self) -> None:
        """Release result data when a future research manager replaces a job."""
        self.keywords.clear()
        self.failures.clear()


def generate_queries(
    seed: str,
    methods: Iterable[str],
    modifiers: Iterable[str] = (),
) -> Iterator[ExpansionQuery]:
    """Yield unique queries in canonical method order, without network calls."""
    normalized_seed = normalize_whitespace(seed)
    if not normalized_seed:
        raise ValueError("seed must not be empty")

    selected = set(methods)
    if not selected:
        raise ValueError("at least one expansion method is required")
    unknown = selected.difference(METHOD_ORDER)
    if unknown:
        raise ValueError(f"unknown expansion method: {sorted(unknown)[0]}")

    seen: set[str] = set()
    for method in METHOD_ORDER:
        if method not in selected:
            continue

        if method == "direct":
            candidates = (normalized_seed,)
        elif method == "alphabet_suffix":
            candidates = (f"{normalized_seed} {letter}" for letter in "abcdefghijklmnopqrstuvwxyz")
        elif method == "alphabet_prefix":
            candidates = (f"{letter} {normalized_seed}" for letter in "abcdefghijklmnopqrstuvwxyz")
        elif method == "numeric_suffix":
            candidates = (f"{normalized_seed} {digit}" for digit in "0123456789")
        elif method == "numeric_prefix":
            candidates = (f"{digit} {normalized_seed}" for digit in "0123456789")
        else:
            # Custom modifiers are suffixes; the caller chooses language-appropriate text.
            candidates = (f"{normalized_seed} {modifier}" for modifier in modifiers)

        for candidate in candidates:
            normalized_query = normalize_whitespace(candidate)
            key = normalized_query.casefold()
            if key not in seen:
                seen.add(key)
                yield ExpansionQuery(normalized_query, method)


async def collect_suggestions(
    seed: str,
    methods: Iterable[str],
    client: GoogleSuggestClient,
    *,
    country: str = "us",
    language: str = "en",
    modifiers: Iterable[str] = (),
    max_requests: int = 500,
) -> ExpansionResult:
    """Run one expansion pass; only returned suggestions become keywords."""
    if isinstance(max_requests, bool) or not isinstance(max_requests, int) or max_requests < 1:
        raise ValueError("max_requests must be a positive integer")

    queries = iter(generate_queries(seed, methods, modifiers))
    result = ExpansionResult()

    while result.requests_attempted < max_requests:
        try:
            expansion_query = next(queries)
        except StopIteration:
            break

        result.queries_generated += 1
        result.requests_attempted += 1
        try:
            suggestions = await client.get_suggestions(
                expansion_query.text, country=country, language=language
            )
        except GoogleSuggestError as exc:
            result.requests_failed += 1
            result.failures.append(
                QueryFailure(expansion_query.text, expansion_query.method, str(exc))
            )
            if isinstance(exc, (GoogleSuggestRateLimited, GoogleSuggestAccessDenied)):
                break
            continue

        result.requests_succeeded += 1
        for suggestion in suggestions:
            # The HTTP client filters empty values; this also supports simple test doubles.
            if not isinstance(suggestion, str) or not suggestion.strip():
                continue
            key = keyword_key(suggestion)
            discovery = Discovery(expansion_query.text, expansion_query.method)
            keyword = result.keywords.get(key)
            if keyword is None:
                result.keywords[key] = DiscoveredKeyword(
                    text=suggestion,
                    first_discovery_query=expansion_query.text,
                    expansion_method=expansion_query.method,
                    discoveries=[discovery],
                )
            elif discovery not in keyword.discoveries:
                keyword.discoveries.append(discovery)

    return result
