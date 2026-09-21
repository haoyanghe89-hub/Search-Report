from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from marketpulse.domain.analysis import MarketAnalysis, QualityResult
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle
from marketpulse.domain.research import ResearchPlan, SearchQuery

AgentRole = Literal["master", "search", "analysis", "report", "harness"]


class SearchTask(BaseModel):
    rationale: str = Field(min_length=1, max_length=1500)
    queries: list[SearchQuery] = Field(min_length=1, max_length=8)


class ReviewDecision(BaseModel):
    action: Literal["research", "report"]
    reason: str = Field(min_length=1, max_length=2000)
    gaps: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def research_requires_gap(self) -> ReviewDecision:
        if self.action == "research" and not self.gaps:
            raise ValueError("research requires at least one concrete gap")
        return self


class ReportParagraph(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    source_ids: list[str] = Field(min_length=1, max_length=30)


class ReportDraft(BaseModel):
    executive_summary: ReportParagraph
    rationale: list[ReportParagraph] = Field(min_length=3, max_length=8)
    next_steps: list[str] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=12)


class BlackboardState(BaseModel):
    schema_version: int = 1
    run_id: str
    version: int = 0
    topic: str
    competitor_limit: int
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    active_agent: AgentRole = "master"
    phase: str = "plan"
    research_round: int = 0
    plan: ResearchPlan | None = None
    search_tasks: list[SearchTask] = Field(default_factory=list)
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    coverage: CoverageSummary | None = None
    analysis: MarketAnalysis | None = None
    reviews: list[ReviewDecision] = Field(default_factory=list)
    draft: ReportDraft | None = None
    quality: QualityResult | None = None
    executed_queries: list[str] = Field(default_factory=list)
    attempted_urls: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    report_path: str | None = None
    error_category: str | None = None
    budget: dict[str, int | float] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BlackboardEvent(BaseModel):
    run_id: str
    version: int
    actor: AgentRole
    event: str
    phase: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
