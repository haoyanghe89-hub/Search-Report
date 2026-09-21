from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from test_workflow import FakeFetcher, FakeRunner, FakeSearch

from marketpulse.agents.team import SearchAgent
from marketpulse.budget import RunBudget
from marketpulse.domain.collaboration import (
    BlackboardState,
    ReportDraft,
    ReviewDecision,
    SearchTask,
)
from marketpulse.domain.research import ResearchPlan, SearchQuery
from marketpulse.errors import NoUsableEvidenceError, WorkflowTimeoutError
from marketpulse.observability import RunLogger
from marketpulse.services.blackboard import BlackboardStore
from marketpulse.workflow import MarketPulseRequest, WorkflowDependencies, run_marketpulse


class RecordingRunner(FakeRunner):
    def __init__(self, *, refine: bool = False, unknown_citation: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.refine = refine
        self.unknown_citation = unknown_citation
        self.search_count = 0

    async def run_json(self, *, schema: type[Any], **kwargs: Any) -> Any:
        payload = json.loads(kwargs["prompt"])
        self.calls.append((kwargs["name"], payload))
        if schema is ReviewDecision and self.refine:
            return ReviewDecision(action="research", reason="需要定价证据", gaps=["核验定价"])
        value = await super().run_json(schema=schema, **kwargs)
        if schema is SearchTask:
            self.search_count += 1
            if self.search_count > 1:
                value.queries = [
                    SearchQuery(id="q1", text="official notes plan pricing", intent="pricing")
                ]
        if schema is ReportDraft and self.unknown_citation:
            value.executive_summary.source_ids = ["S999"]
        return value


async def run_team(tmp_path: Path, settings: Any, runner: Any) -> tuple[Any, BlackboardStore]:
    board = BlackboardStore(settings.database_url.get_secret_value())
    budget = RunBudget.start(settings)
    deps = WorkflowDependencies(
        search=FakeSearch(),
        fetcher=FakeFetcher(budget),
        runner=runner,
        budget=budget,
        logger=RunLogger("run_multi"),
        blackboard=board,
    )
    result = await run_marketpulse(
        MarketPulseRequest(topic="AI meeting notes", output_path=tmp_path / "result.md"),
        deps,
        settings,
    )
    return result, board


@pytest.mark.asyncio
async def test_four_roles_exchange_committed_state_and_preserve_facts(
    tmp_path: Path,
    settings: Any,
) -> None:
    runner = RecordingRunner()
    result, board = await run_team(tmp_path, settings, runner)
    names = [name for name, _ in runner.calls]
    assert names == [
        "MarketPulse Master",
        "MarketPulse Search",
        "MarketPulse Analyst",
        "MarketPulse Master",
        "MarketPulse Reporter",
    ]
    state = board.load("run_multi")
    assert state.status == "completed"
    assert state.draft and state.analysis
    assert state.analysis.confidence == result.analysis.confidence == 0.55
    assert state.analysis.competitors == result.analysis.competitors
    assert state.analysis.recommendation == result.analysis.recommendation
    assert state.analysis.executive_summary != result.analysis.executive_summary
    assert "[S1](#s1)" in result.report_markdown
    assert result.report_markdown.count("\n## ") == 10
    assert result.state_version == state.version
    assert state.budget["pages_used"] == 4
    assert {e.actor for e in result.agent_events} >= {"master", "search", "analysis", "report"}
    assert "test-key" not in state.model_dump_json()
    board.close()


@pytest.mark.asyncio
async def test_master_refinement_bounded_and_duplicate_urls_not_refetched(
    tmp_path: Path,
    settings: Any,
) -> None:
    runner = RecordingRunner(refine=True)
    result, board = await run_team(tmp_path, settings, runner)
    state = board.load("run_multi")
    assert state.research_round == settings.max_research_rounds == 2
    assert result.stats.pages_succeeded == 4
    assert len(state.attempted_urls) == len(set(state.attempted_urls)) == 4
    assert len(state.evidence.sources) == 4
    second_search = [p for n, p in runner.calls if n == "MarketPulse Search"][1]
    assert second_search["gaps"] == ["核验定价"]
    assert "未解决：核验定价" in result.report_markdown
    assert any(e.event == "research.budget_limited" for e in result.agent_events)
    board.close()


@pytest.mark.asyncio
async def test_report_unknown_citation_fails_and_keeps_analysis(
    tmp_path: Path,
    settings: Any,
) -> None:
    with pytest.raises(NoUsableEvidenceError, match="未知来源"):
        await run_team(tmp_path, settings, RecordingRunner(unknown_citation=True))
    board = BlackboardStore(settings.database_url.get_secret_value())
    state = board.load("run_multi")
    assert state.status == "failed" and state.analysis is not None
    assert state.draft is None and state.report_path is None
    assert not (tmp_path / "result.md").exists()
    assert board.history(state.run_id)[-1].event == "run.failed"
    board.close()


@pytest.mark.asyncio
async def test_timeout_saved_without_exception_payload(tmp_path: Path, settings: Any) -> None:
    class SlowRunner:
        async def run_json(self, **kwargs: Any) -> Any:
            await asyncio.sleep(10)

    settings.total_timeout_seconds = 0.05
    with pytest.raises(WorkflowTimeoutError, match="0.05"):
        await run_team(tmp_path, settings, SlowRunner())
    board = BlackboardStore(settings.database_url.get_secret_value())
    state = board.load("run_multi")
    assert state.status == "failed" and state.error_category == "TimeoutError"
    board.close()


@pytest.mark.asyncio
async def test_cancellation_keeps_terminal_state(tmp_path: Path, settings: Any) -> None:
    started = asyncio.Event()

    class SlowRunner:
        async def run_json(self, **kwargs: Any) -> Any:
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(run_team(tmp_path, settings, SlowRunner()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    board = BlackboardStore(settings.database_url.get_secret_value())
    assert board.load("run_multi").status == "cancelled"
    board.close()


@pytest.mark.asyncio
async def test_search_rejects_only_repeated_queries() -> None:
    runner = FakeRunner()
    plan = await runner.run_json(schema=ResearchPlan)
    state = BlackboardState(
        run_id="r",
        topic="meeting notes",
        competitor_limit=3,
        plan=plan,
        executed_queries=[q.text.upper() for q in plan.queries],
    )
    with pytest.raises(NoUsableEvidenceError, match="新的有效查询"):
        await SearchAgent(runner).prepare(state, 4)
