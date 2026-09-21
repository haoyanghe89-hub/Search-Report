from __future__ import annotations

from typing import TYPE_CHECKING

from marketpulse.adapters.search import canonicalize_url
from marketpulse.agents.team import AnalysisAgent, MasterAgent, ReportAgent, SearchAgent
from marketpulse.config import Settings
from marketpulse.domain.collaboration import AgentRole, BlackboardState
from marketpulse.domain.evidence import PageEvidence
from marketpulse.errors import NoUsableEvidenceError
from marketpulse.observability import RunStats, Stage
from marketpulse.services.blackboard import BlackboardStore
from marketpulse.services.collector import collect_candidates, fetch_candidates
from marketpulse.services.evidence_store import EvidenceStore
from marketpulse.services.extractor import build_page_evidence
from marketpulse.services.notifications import ProgressNotifier
from marketpulse.services.quality import evaluate_quality
from marketpulse.services.reporter import apply_report_draft, render_report, write_report_atomic

if TYPE_CHECKING:
    from marketpulse.workflow import MarketPulseRequest, MarketPulseResult, WorkflowDependencies


class TeamCoordinator:
    """The harness dispatches roles, enforces budgets, and commits their typed outputs."""

    def __init__(
        self,
        deps: WorkflowDependencies,
        settings: Settings,
        board: BlackboardStore,
        notifier: ProgressNotifier,
        state: BlackboardState,
    ) -> None:
        self.deps, self.settings, self.board, self.notifier = deps, settings, board, notifier
        self.state = state
        self.stats = RunStats(run_id=state.run_id)
        self.master = MasterAgent(deps.runner)
        self.search = SearchAgent(deps.runner)
        self.analyst = AnalysisAgent(deps.runner)
        self.reporter = ReportAgent(deps.runner)

    async def commit(self, actor: AgentRole, event: str) -> None:
        budget = self.deps.budget
        self.state.budget = {
            "search_queries_used": budget.search_queries_used,
            "pages_used": budget.pages_used,
            "remaining_seconds": round(budget.remaining_seconds, 2),
            "max_search_queries": budget.max_search_queries,
            "max_pages": budget.max_pages,
        }
        record = self.board.save(self.state, actor, event)
        await self.notifier.publish(record)
        self.state = self.board.load(self.state.run_id)

    async def stage(self, stage: Stage, actor: AgentRole) -> None:
        self.deps.budget.ensure_time_remaining()
        self.state.phase, self.state.active_agent = stage.value, actor
        self.deps.logger.event(stage, "started", agent=actor, round=self.state.research_round)
        if self.deps.progress:
            self.deps.progress(stage)
        await self.commit(actor, f"{stage.value}.started")

    async def gather_evidence(self) -> None:
        await self.stage(Stage.SEARCH, "search")
        budget = self.deps.budget
        remaining_queries = min(
            budget.max_search_queries - budget.search_queries_used,
            budget.max_search_queries - len(self.state.executed_queries),
        )
        if self.state.research_round == 0 and self.settings.max_research_rounds > 1:
            remaining_queries = max(1, remaining_queries // 2)
        task = await self.search.prepare(
            self.state,
            min(self.settings.max_initial_queries, remaining_queries),
        )
        self.state.research_round += 1
        self.state.search_tasks.append(task)
        self.state.executed_queries.extend(q.text for q in task.queries)
        await self.commit("search", "search.queries_selected")
        candidates, search_warnings = await collect_candidates(task.queries, self.deps.search)
        self.stats.search_queries = budget.search_queries_used
        self.stats.candidates += len(candidates)
        await self.stage(Stage.FETCH, "search")
        attempted = set(self.state.attempted_urls)
        fresh = [c for c in candidates if canonicalize_url(str(c.url)) not in attempted]
        page_limit = budget.max_pages - budget.pages_used
        if self.state.research_round == 1 and self.settings.max_research_rounds > 1:
            page_limit = max(1, page_limit // 2)
        fresh = fresh[:page_limit]
        self.state.attempted_urls.extend(canonicalize_url(str(c.url)) for c in fresh)
        await self.commit("search", "fetch.urls_selected")
        pages, fetch_warnings = await fetch_candidates(
            fresh,
            self.deps.fetcher,
            max_pages=page_limit,
            concurrency=self.settings.max_fetch_concurrency,
        )
        self.stats.pages_succeeded += len(pages)
        self.stats.pages_failed += len(fetch_warnings)
        await self.stage(Stage.EXTRACT, "search")
        store = EvidenceStore()
        for source in self.state.evidence.sources:
            store.add(
                PageEvidence(
                    source=source,
                    claims=[c for c in self.state.evidence.claims if c.source_id == source.id],
                )
            )
        first_id = max((int(s.id[1:]) for s in self.state.evidence.sources), default=0) + 1
        for index, page in enumerate(pages, start=first_id):
            try:
                store.add(build_page_evidence(page, index))
            except ValueError:
                store.warn(f"页面证据结构无效: {page.final_url}")
        for warning in [*self.state.evidence.warnings, *search_warnings, *fetch_warnings]:
            store.warn(warning)
        if not fresh and self.state.research_round > 1:
            store.warn("补查未发现新的可抓取页面，保留已获得的证据。")
        self.state.evidence, self.state.coverage = store.bundle(), store.coverage()
        self.state.warnings = list(dict.fromkeys([*self.state.warnings, *store.bundle().warnings]))
        self.stats.sources = self.state.coverage.unique_sources
        await self.commit("search", "search.evidence_ready")
        if not self.state.evidence.claims:
            raise NoUsableEvidenceError("未获得可追溯的页面正文证据，停止生成报告。")

    def can_research(self) -> bool:
        budget = self.deps.budget
        return (
            self.state.research_round < self.settings.max_research_rounds
            and len(self.state.executed_queries) < budget.max_search_queries
            and budget.search_queries_used < budget.max_search_queries
            and budget.pages_used < budget.max_pages
            and budget.remaining_seconds > 120
        )

    async def run(self, request: MarketPulseRequest) -> MarketPulseResult:
        from marketpulse.workflow import MarketPulseResult

        await self.stage(Stage.PLAN, "master")
        self.state.plan = await self.master.plan(self.state)
        await self.commit("master", "plan.completed")
        while True:
            await self.gather_evidence()
            await self.stage(Stage.ANALYZE, "analysis")
            self.state.analysis = await self.analyst.analyze(self.state)
            await self.commit("analysis", "analysis.completed")
            await self.stage(Stage.REVIEW, "master")
            decision = await self.master.review(
                self.state,
                self.deps.budget,
                self.settings.max_research_rounds,
            )
            self.state.reviews.append(decision)
            await self.commit("master", "review.completed")
            if decision.action == "report":
                break
            if not self.can_research():
                self.state.warnings.append(
                    "补查受轮次/时间/查询/页面预算限制，报告保留未解决问题。"
                )
                self.state.warnings.extend(f"未解决：{gap}" for gap in decision.gaps)
                await self.commit("harness", "research.budget_limited")
                break

        await self.stage(Stage.QUALITY, "harness")
        assert self.state.analysis is not None and self.state.coverage is not None
        self.state.quality = evaluate_quality(
            self.state.evidence,
            self.state.coverage,
            self.state.analysis,
        )
        if not self.state.quality.passed:
            raise NoUsableEvidenceError("报告未通过质量检查。")
        await self.commit("harness", "quality.completed")
        await self.stage(Stage.REPORT, "report")
        self.state.draft = await self.reporter.compose(self.state)
        await self.commit("report", "report.drafted")
        await self.stage(Stage.WRITE, "report")
        assert self.state.analysis and self.state.draft and self.state.plan
        assert self.state.coverage and self.state.quality
        presented = apply_report_draft(self.state.analysis, self.state.draft)
        presented.limitations = list(
            dict.fromkeys(
                [
                    *presented.limitations,
                    *self.state.warnings,
                ]
            )
        )
        markdown = render_report(
            self.state.plan,
            self.state.evidence,
            self.state.coverage,
            presented,
            self.state.quality,
            executed_query_count=len(self.state.executed_queries),
        )
        path = write_report_atomic(markdown, request.output_path)
        self.state.report_path, self.state.status = str(path), "completed"
        self.state.phase = "completed"
        await self.commit("report", "run.completed")
        assert self.state.quality and self.state.coverage
        assert self.state.draft
        # The existing web UI renders prose as text; Markdown links belong in the artifact.
        api_analysis = presented.model_copy(
            update={
                "executive_summary": self.state.draft.executive_summary.text,
                "rationale": [p.text for p in self.state.draft.rationale],
            }
        )
        self.stats.warnings = self.state.warnings
        return MarketPulseResult(
            run_id=self.state.run_id,
            report_path=path,
            quality=self.state.quality,
            stats=self.stats,
            analysis=api_analysis,
            evidence=self.state.evidence,
            coverage=self.state.coverage,
            report_markdown=markdown,
            agent_events=self.board.history(self.state.run_id),
            state_version=self.state.version,
            storage_backend=self.board.backend,
        )
