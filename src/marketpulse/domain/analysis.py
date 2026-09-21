from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Recommendation(StrEnum):
    GO = "Go"
    CONDITIONAL_GO = "Conditional Go"
    NO_GO = "No-Go"


class Pricing(BaseModel):
    summary: str
    source_ids: list[str] = Field(default_factory=list)
    verified: bool = False


class Competitor(BaseModel):
    name: str
    positioning: str
    target_customers: str
    key_features: list[str]
    pricing: Pricing
    source_ids: list[str] = Field(min_length=1)


class MarketSignal(BaseModel):
    statement: str
    interpretation: str
    source_ids: list[str] = Field(min_length=1)


class MarketAnalysis(BaseModel):
    executive_summary: str
    market_signals: list[MarketSignal] = Field(min_length=1)
    competitors: list[Competitor] = Field(min_length=1, max_length=5)
    opportunities: list[str] = Field(min_length=1)
    barriers: list[str] = Field(min_length=1)
    recommendation: Recommendation
    confidence: float = Field(ge=0, le=1)
    rationale: list[str] = Field(min_length=3)
    risks: list[str] = Field(min_length=1)
    next_steps: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("competitors")
    @classmethod
    def cap_competitors(cls, competitors: list[Competitor]) -> list[Competitor]:
        return competitors[:5]


class QualityIssue(BaseModel):
    code: str
    message: str
    fatal: bool = False


class QualityResult(BaseModel):
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)
