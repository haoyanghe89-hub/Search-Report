from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from marketpulse.adapters.fetch import FetchedPage
from marketpulse.budget import RunBudget
from marketpulse.domain.analysis import (
    Competitor,
    MarketAnalysis,
    MarketSignal,
    Pricing,
    Recommendation,
)
from marketpulse.domain.collaboration import (
    ReportDraft,
    ReportParagraph,
    ReviewDecision,
    SearchTask,
)
from marketpulse.domain.research import ResearchPlan, SearchCandidate, SearchQuery
from marketpulse.observability import RunLogger
from marketpulse.workflow import (
    MarketPulseRequest,
    WorkflowDependencies,
    run_marketpulse,
)


class FakeRunner:
    async def run_json(self, *, schema: type[Any], **_: Any) -> Any:
        if schema is SearchTask:
            return SearchTask(
                rationale="覆盖市场与定价",
                queries=[
                    SearchQuery(id="q1", text="meeting notes demand", intent="demand"),
                    SearchQuery(id="q2", text="meeting notes competitors", intent="competitor"),
                    SearchQuery(id="q3", text="meeting notes products", intent="product"),
                    SearchQuery(id="q4", text="meeting notes pricing", intent="pricing"),
                ],
            )
        if schema is ReviewDecision:
            return ReviewDecision(action="report", reason="现有证据支持带局限性报告")
        if schema is ReportDraft:
            return ReportDraft(
                executive_summary=ReportParagraph(
                    text="有条件进入，优先验证差异化。", source_ids=["S1"]
                ),
                rationale=[
                    ReportParagraph(text=t, source_ids=["S1"])
                    for t in ["有公开产品", "有付费机制", "需要验证差异化"]
                ],
                next_steps=["访谈目标客户"],
                limitations=["覆盖有限"],
            )
        if schema is ResearchPlan:
            return ResearchPlan(
                original_topic="AI meeting notes tools",
                normalized_topic="AI meeting notes tools",
                research_questions=["demand", "competitors", "pricing"],
                queries=[
                    SearchQuery(id="q1", text="meeting notes demand", intent="demand"),
                    SearchQuery(id="q2", text="meeting notes competitors", intent="competitor"),
                    SearchQuery(id="q3", text="meeting notes products", intent="product"),
                    SearchQuery(id="q4", text="meeting notes pricing", intent="pricing"),
                ],
            )
        return MarketAnalysis(
            executive_summary="可进入，但需要明确差异化。",
            market_signals=[
                MarketSignal(
                    statement="存在公开订阅价格。",
                    interpretation="付费成熟。",
                    source_ids=["S1"],
                )
            ],
            competitors=[
                Competitor(
                    name="Acme",
                    positioning="会议助手",
                    target_customers="团队",
                    key_features=["转录"],
                    pricing=Pricing(summary="$20/month", source_ids=["S1"], verified=True),
                    source_ids=["S1"],
                )
            ],
            opportunities=["垂直工作流"],
            barriers=["竞争激烈"],
            recommendation=Recommendation.CONDITIONAL_GO,
            confidence=0.8,
            rationale=["需求存在", "有付费", "需要差异化"],
            risks=["同质化"],
            next_steps=["用户访谈"],
            limitations=[],
        )


class FakeSearch:
    async def search(self, query: SearchQuery, *, limit: int = 8) -> list[SearchCandidate]:
        return [
            SearchCandidate(
                query_id=query.id,
                title=f"Acme {query.intent}",
                url=f"https://acme.example/{query.intent}",
                rank=1,
                source_hint="official",
            )
        ]


class FakeFetcher:
    def __init__(self, budget: RunBudget) -> None:
        self.budget = budget

    async def fetch(self, candidate: SearchCandidate) -> FetchedPage:
        self.budget.reserve_page()
        return FetchedPage(
            candidate=candidate,
            final_url=str(candidate.url),
            content_type="text/html",
            body=(
                b"<main><p>Professional teams pay $20 per month for automated transcription "
                b"and meeting summaries with calendar integrations.</p></main>"
            ),
            fetched_at=datetime(2026, 9, 17, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_offline_workflow_generates_report(tmp_path: Path, settings: Any) -> None:
    budget = RunBudget.start(settings)
    output = tmp_path / "report.md"
    deps = WorkflowDependencies(
        search=FakeSearch(),
        fetcher=FakeFetcher(budget),  # type: ignore[arg-type]
        runner=FakeRunner(),
        budget=budget,
        logger=RunLogger("run_test"),
    )
    result = await run_marketpulse(
        MarketPulseRequest(topic="AI meeting notes tools", output_path=output),
        deps,
        settings,
    )
    assert result.report_path == output.resolve()
    assert output.exists()
    assert "## 10. 局限性与未验证信息" in output.read_text(encoding="utf-8")
    assert result.stats.search_queries == 0  # fake search does not consume the production budget
    assert result.analysis.recommendation is Recommendation.CONDITIONAL_GO
    assert result.coverage.unique_sources >= 1
    assert result.evidence.sources
    assert result.report_markdown.startswith("# ")
