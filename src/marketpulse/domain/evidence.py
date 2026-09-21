from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, model_validator


class SourceType(StrEnum):
    OFFICIAL = "official"
    RESEARCH = "research"
    MEDIA = "media"
    OTHER = "other"


class Source(BaseModel):
    id: str = Field(pattern=r"^S\d+$")
    url: HttpUrl
    title: str
    domain: str
    source_type: SourceType
    accessed_at: datetime
    query_id: str


class EvidenceClaim(BaseModel):
    id: str = Field(pattern=r"^C\d+(?:_\d+)?$")
    source_id: str = Field(pattern=r"^S\d+$")
    claim_type: str
    subject: str
    statement: str = Field(min_length=10, max_length=1000)
    quote: str = Field(min_length=10, max_length=500)


class PageEvidence(BaseModel):
    source: Source
    claims: list[EvidenceClaim] = Field(default_factory=list)
    extracted_text: str = Field(default="", exclude=True)


class EvidenceBundle(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def claims_reference_known_sources(self) -> EvidenceBundle:
        source_ids = {source.id for source in self.sources}
        unknown = {claim.source_id for claim in self.claims} - source_ids
        if unknown:
            raise ValueError(f"unknown source ids: {sorted(unknown)}")
        return self


class CoverageSummary(BaseModel):
    unique_sources: int
    official_sources: int
    claim_count: int
    pricing_claims: int
    low_coverage: bool
