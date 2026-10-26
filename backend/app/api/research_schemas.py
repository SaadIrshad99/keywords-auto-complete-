"""Validation and response shapes for the local research API."""

import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.research.job_manager import JobProgress, ResearchConfig
from app.services.keyword_expansion import METHOD_ORDER, normalize_whitespace


ExpansionMethod = Literal[
    "direct", "alphabet_suffix", "alphabet_prefix", "numeric_suffix",
    "numeric_prefix", "modifier_suffix",
]
Relevance = Literal["seed_phrase", "seed_terms", "none"]


class ResearchRequest(BaseModel):
    seed: str = Field(max_length=200)
    country: str = "us"
    language: str = "en"
    max_depth: int = Field(default=2, ge=1, le=4, strict=True)
    max_requests: int = Field(default=500, ge=1, le=10000, strict=True)
    max_keywords: int = Field(default=10000, ge=1, le=100000, strict=True)
    max_pending_queue: int = Field(default=1000, ge=1, le=100000, strict=True)
    request_delay: float = Field(default=1.5, ge=0, le=60)
    methods: list[ExpansionMethod] = Field(default_factory=lambda: ["direct"])
    modifiers: list[str] = Field(default_factory=list, max_length=50)
    relevance: Relevance = "seed_phrase"

    @field_validator("seed")
    @classmethod
    def validate_seed(cls, value: str) -> str:
        value = normalize_whitespace(value)
        if not value:
            raise ValueError("seed must not be empty")
        return value

    @field_validator("country")
    @classmethod
    def validate_country(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2}", value):
            raise ValueError("country must be a two-letter code")
        return value

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", value):
            raise ValueError("language must be a language code such as en or pt-br")
        return value

    @field_validator("request_delay")
    @classmethod
    def validate_delay(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("request_delay must be finite")
        return value

    @field_validator("methods")
    @classmethod
    def validate_methods(cls, value: list[ExpansionMethod]) -> list[ExpansionMethod]:
        if not value:
            raise ValueError("at least one expansion method is required")
        return sorted(set(value), key=METHOD_ORDER.index)

    @field_validator("modifiers")
    @classmethod
    def validate_modifiers(cls, value: list[str]) -> list[str]:
        normalized = [normalize_whitespace(item) for item in value]
        if any(not item for item in normalized):
            raise ValueError("modifiers must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_modifier_method(self) -> "ResearchRequest":
        if "modifier_suffix" in self.methods and not self.modifiers:
            raise ValueError("modifier_suffix requires at least one modifier")
        return self

    def to_config(self) -> ResearchConfig:
        return ResearchConfig(
            seed=self.seed,
            methods=tuple(self.methods),
            country=self.country,
            language=self.language,
            modifiers=tuple(self.modifiers),
            max_depth=self.max_depth,
            max_requests=self.max_requests,
            max_keywords=self.max_keywords,
            max_pending_queue=self.max_pending_queue,
            request_delay=self.request_delay,
            relevance=self.relevance,
        )


class JobResponse(BaseModel):
    job_id: str
    status: str
    seed: str
    country: str
    language: str
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

    @classmethod
    def from_progress(cls, progress: JobProgress) -> "JobResponse":
        return cls.model_validate(progress, from_attributes=True)


class DiscoveryResponse(BaseModel):
    parent_keyword: str
    query: str
    method: str
    depth: int


class KeywordResponse(BaseModel):
    keyword: str
    depth: int
    first_discovery_query: str
    expansion_method: str
    discoveries: list[DiscoveryResponse]


class KeywordPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[KeywordResponse]
