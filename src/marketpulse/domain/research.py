from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

SearchIntent = Literal["demand", "competitor", "product", "pricing", "trend"]


class SearchQuery(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=3, max_length=300)
    intent: SearchIntent


class ResearchPlan(BaseModel):
    original_topic: str = Field(min_length=2, max_length=200)
    normalized_topic: str = Field(min_length=2, max_length=200)
    research_questions: list[str] = Field(min_length=3, max_length=8)
    queries: list[SearchQuery] = Field(min_length=4, max_length=12)

    @field_validator("queries")
    @classmethod
    def unique_queries(cls, queries: list[SearchQuery]) -> list[SearchQuery]:
        normalized = [query.text.casefold().strip() for query in queries]
        if len(normalized) != len(set(normalized)):
            raise ValueError("search queries must be unique")
        return queries


class SearchCandidate(BaseModel):
    query_id: str
    title: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    snippet: str = Field(default="", max_length=2000)
    rank: int = Field(ge=1)
    source_hint: Literal["official", "research", "media", "other"] = "other"


class SearchBatch(BaseModel):
    query_id: str
    candidates: list[SearchCandidate] = Field(default_factory=list)
