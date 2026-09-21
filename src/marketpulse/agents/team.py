from __future__ import annotations

import json
import re

from marketpulse.agents.factory import AgentRunner
from marketpulse.agents.prompts import (
    MASTER_REVIEW_INSTRUCTIONS,
    REPORTER_INSTRUCTIONS,
    SEARCH_INSTRUCTIONS,
)
from marketpulse.budget import RunBudget
from marketpulse.domain.analysis import MarketAnalysis
from marketpulse.domain.collaboration import (
    BlackboardState,
    ReportDraft,
    ReviewDecision,
    SearchTask,
)
from marketpulse.domain.research import ResearchPlan, SearchQuery
from marketpulse.errors import NoUsableEvidenceError
from marketpulse.services.analyzer import analyze_market
from marketpulse.services.planner import create_research_plan


class MasterAgent:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    async def plan(self, state: BlackboardState) -> ResearchPlan:
        return await create_research_plan(state.topic, state.competitor_limit, self.runner)

    async def review(
        self,
        state: BlackboardState,
        budget: RunBudget,
        max_rounds: int,
    ) -> ReviewDecision:
        return await self.runner.run_json(
            name="MarketPulse Master",
            instructions=MASTER_REVIEW_INSTRUCTIONS,
            prompt=json.dumps(
                {
                    "analysis": state.analysis.model_dump(mode="json") if state.analysis else None,
                    "coverage": state.coverage.model_dump() if state.coverage else None,
                    "warnings": state.warnings[-20:],
                    "research_round": state.research_round,
                    "max_rounds": max_rounds,
                    "searches_remaining": budget.max_search_queries - budget.search_queries_used,
                    "pages_remaining": budget.max_pages - budget.pages_used,
                    "seconds_remaining": round(budget.remaining_seconds),
                },
                ensure_ascii=False,
            ),
            schema=ReviewDecision,
        )


class SearchAgent:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    async def prepare(self, state: BlackboardState, query_limit: int) -> SearchTask:
        if state.plan is None:
            raise ValueError("Master plan is required")
        task = await self.runner.run_json(
            name="MarketPulse Search",
            instructions=SEARCH_INSTRUCTIONS,
            prompt=json.dumps(
                {
                    "plan": state.plan.model_dump(mode="json"),
                    "gaps": state.reviews[-1].gaps if state.reviews else [],
                    "known_sources": [s.model_dump(mode="json") for s in state.evidence.sources],
                    "executed_queries": state.executed_queries,
                    "max_queries": query_limit,
                },
                ensure_ascii=False,
            ),
            schema=SearchTask,
        )
        seen = {" ".join(q.casefold().split()) for q in state.executed_queries}
        queries: list[SearchQuery] = []
        for query in task.queries:
            key = " ".join(query.text.casefold().split())
            if key not in seen and len(queries) < query_limit:
                seen.add(key)
                queries.append(
                    query.model_copy(
                        update={"id": f"r{state.research_round + 1}q{len(queries) + 1}"}
                    )
                )
        if not queries:
            raise NoUsableEvidenceError("搜索 Agent 未提供新的有效查询。")
        return task.model_copy(update={"queries": queries})


class AnalysisAgent:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    async def analyze(self, state: BlackboardState) -> MarketAnalysis:
        if state.plan is None or state.coverage is None:
            raise ValueError("Research plan and coverage are required")
        return await analyze_market(
            state.plan.normalized_topic,
            state.evidence,
            state.coverage,
            state.competitor_limit,
            self.runner,
        )


def validate_draft(draft: ReportDraft, state: BlackboardState) -> ReportDraft:
    known = {source.id for source in state.evidence.sources}
    paragraphs = [draft.executive_summary, *draft.rationale]
    unknown = {s for paragraph in paragraphs for s in paragraph.source_ids} - known
    if unknown:
        raise NoUsableEvidenceError(f"报告 Agent 引用了未知来源: {sorted(unknown)}")
    texts = [p.text for p in paragraphs] + draft.next_steps + draft.limitations
    if any(re.search(r"https?://|<[^>]*>|\]\(|\[S\d+\]|^\s*#", t, re.M) for t in texts):
        raise NoUsableEvidenceError("报告 Agent 必须返回正文；引用由程序统一生成。")
    return draft


class ReportAgent:
    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner

    async def compose(self, state: BlackboardState) -> ReportDraft:
        if state.analysis is None:
            raise ValueError("Analysis required before report")
        draft = await self.runner.run_json(
            name="MarketPulse Reporter",
            instructions=REPORTER_INSTRUCTIONS,
            prompt=json.dumps(
                {
                    "analysis": state.analysis.model_dump(mode="json"),
                    "sources": [s.model_dump(mode="json") for s in state.evidence.sources],
                    "coverage": state.coverage.model_dump() if state.coverage else None,
                    "warnings": state.warnings[-20:],
                },
                ensure_ascii=False,
            ),
            schema=ReportDraft,
        )
        return validate_draft(draft, state)
