from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from marketpulse.adapters.fetch import PageFetcher
from marketpulse.adapters.search import SearchClient
from marketpulse.agents.factory import AgentRunner
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.analysis import MarketAnalysis, QualityResult
from marketpulse.domain.collaboration import BlackboardEvent, BlackboardState
from marketpulse.domain.evidence import CoverageSummary, EvidenceBundle
from marketpulse.errors import WorkflowTimeoutError
from marketpulse.observability import RunLogger, RunStats, Stage
from marketpulse.services.blackboard import BlackboardStore
from marketpulse.services.notifications import ProgressNotifier
from marketpulse.services.planner import validate_topic


class MarketPulseRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    competitor_limit: int = Field(default=5, ge=3, le=8)
    output_path: Path


@dataclass
class WorkflowDependencies:
    search: SearchClient
    fetcher: PageFetcher
    runner: AgentRunner
    budget: RunBudget
    logger: RunLogger
    progress: Callable[[Stage], None] | None = None
    blackboard: BlackboardStore | None = None


@dataclass
class MarketPulseResult:
    run_id: str
    report_path: Path
    quality: QualityResult
    stats: RunStats
    analysis: MarketAnalysis
    evidence: EvidenceBundle
    coverage: CoverageSummary
    report_markdown: str
    agent_events: list[BlackboardEvent] = field(default_factory=list)
    state_version: int = 0
    storage_backend: str = "sqlite"


async def run_marketpulse(
    request: MarketPulseRequest,
    deps: WorkflowDependencies,
    settings: Settings,
) -> MarketPulseResult:
    from marketpulse.services.coordinator import TeamCoordinator

    topic = validate_topic(request.topic)
    board = deps.blackboard or BlackboardStore(settings.database_url.get_secret_value())
    notifier = ProgressNotifier(
        settings.redis_url.get_secret_value() if settings.redis_url else None
    )
    state = BlackboardState(
        run_id=deps.logger.run_id,
        topic=topic,
        competitor_limit=request.competitor_limit,
    )
    created = False
    try:
        board.create(state)
        created = True
        async with asyncio.timeout(settings.total_timeout_seconds):
            return await TeamCoordinator(deps, settings, board, notifier, state).run(request)
    except BaseException as exc:
        if created:
            try:
                state = board.load(state.run_id)
                state.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
                state.error_category = type(exc).__name__
                board.save(state, "harness", f"run.{state.status}")
            except Exception:
                logging.getLogger("marketpulse").error("Could not persist terminal run status")
        if isinstance(exc, TimeoutError):
            raise WorkflowTimeoutError(
                f"MarketPulse 超过 {settings.total_timeout_seconds:g} 秒总时限。"
            ) from exc
        raise
    finally:
        await notifier.aclose()
        if deps.blackboard is None:
            board.close()
