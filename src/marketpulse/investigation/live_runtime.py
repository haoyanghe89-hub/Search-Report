"""Owned background LIVE runs using the same persisted agent workflow as replay."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.adapters.investigation_search import PublicSearchPortAdapter
from marketpulse.adapters.search import PublicSearchClient
from marketpulse.budget import RunBudget as SearchBudget
from marketpulse.config import Settings
from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.adapters.fetch import HttpxFetchAdapter
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.domain.enums import (
    ExecutionStepStatus,
    ReportType,
    RunMode,
    RunStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import Investigation, InvestigationRun, RunBudget
from marketpulse.investigation.feedback.models import FeedbackLoopConfig
from marketpulse.investigation.feedback.orchestrator import AgentFeedbackOrchestrator
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.harness.runtime import InvestigationHarness
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.models import ExecutionStepRow, InvestigationRunRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import FetchPort, ModelPort, SearchPort
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from marketpulse.investigation.reporting.pipeline import ReportPipeline
from marketpulse.investigation.reporting.writer import DeterministicWriter
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import RecognizedArtifactVersions
from marketpulse.investigation.validation.policy import ValidationPolicy

LOGGER = logging.getLogger(__name__)
_ACTIVE = {
    RunStatus.CREATED,
    RunStatus.PENDING,
    RunStatus.WAITING_FOR_EXECUTION,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
}


class LiveNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class LivePorts:
    """Injection boundary for offline integration tests and alternative providers."""

    search: SearchPort
    fetch: FetchPort
    model: ModelPort


class LiveInvestigationService:
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        settings: Settings,
        blob_root: Path,
        ports: LivePorts | None = None,
    ) -> None:
        self.sessions = sessions
        self.repository = repository
        self.settings = settings
        self.blobs = LocalContentAddressedBlobStorage(blob_root)
        self.ports = ports
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._closing = False
        self.worker_activity: dict[str, dict[str, str]] = {}

    def recover_interrupted(self) -> None:
        """Single-worker API: abandoned jobs must not look like running work forever."""
        with self.sessions.begin() as session:
            rows = session.scalars(
                select(InvestigationRunRow).where(
                    InvestigationRunRow.mode == RunMode.LIVE,
                    InvestigationRunRow.status.in_(_ACTIVE),
                )
            ).all()
            for row in rows:
                row.status = RunStatus.INTERRUPTED
                row.interruption_reason = "SERVER_RESTARTED: start a new run to retry"
                row.updated_at = datetime.now(UTC)
                row.completed_at = row.updated_at
                row.owner_instance_id = None
                row.owner_heartbeat_at = None
                steps = session.scalars(
                    select(ExecutionStepRow).where(
                        ExecutionStepRow.run_id == row.run_id,
                        ExecutionStepRow.status == ExecutionStepStatus.RUNNING,
                    )
                ).all()
                for step in steps:
                    step.status = ExecutionStepStatus.INTERRUPTED
                    step.error_code = "SERVER_RESTARTED"
                    step.completed_at = row.updated_at

    def start(self, investigation_id: str) -> str:
        if self._closing:
            raise LiveNotConfiguredError("服务正在关闭，请稍后重试。")
        key = self.settings.deepseek_api_key
        if self.ports is None and (key is None or not key.get_secret_value().strip()):
            raise LiveNotConfiguredError(
                "实时调查需要模型凭据：请配置 DEEPSEEK_API_KEY 后重启服务；"
                "DEEPSEEK_BASE_URL 和 MARKETPULSE_MODEL 可用于兼容的模型服务。"
            )
        self.repository.get(Investigation, investigation_id)
        run_id = f"RUN-LIVE-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)
        self.repository.add(
            InvestigationRun(
                run_id=run_id,
                investigation_id=investigation_id,
                mode=RunMode.LIVE,
                status=RunStatus.CREATED,
                current_phase=WorkflowPhase.CREATED,
                checkpoint_version=0,
                state_version=0,
                workflow_version="parallel-research-v2",
                created_at=now,
                started_at=now,
                updated_at=now,
            )
        )
        HarnessStore(self.sessions, self.repository).install_budget(
            RunBudget(
                run_id=run_id,
                max_research_rounds=self.settings.max_research_rounds,
                max_search_calls=self.settings.max_search_queries,
                max_fetch_calls=self.settings.max_pages,
                max_model_calls=self.settings.max_model_calls,
                max_tokens=self.settings.max_tokens,
                max_wall_time_ms=int(self.settings.total_timeout_seconds * 1000),
                max_sources=self.settings.max_pages,
                updated_at=now,
            )
        )
        self.worker_activity[run_id] = {}
        task = asyncio.create_task(self._execute(run_id), name=run_id)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        task.add_done_callback(lambda _: self.worker_activity.pop(run_id, None))
        return run_id

    async def cancel(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._finish(run_id, RunStatus.CANCELLED, "USER_CANCELLED")
        return True

    async def shutdown(self) -> None:
        self._closing = True
        pending = tuple((run_id, task) for run_id, task in self.tasks.items() if not task.done())
        for _, task in pending:
            task.cancel()
        await asyncio.gather(*(task for _, task in pending), return_exceptions=True)
        for run_id, _ in pending:
            self._finish(run_id, RunStatus.INTERRUPTED, "SERVER_SHUTDOWN: start a new run to retry")

    async def _execute(self, run_id: str) -> None:
        try:
            async with AsyncExitStack() as stack:
                ports = self.ports
                if ports is None:
                    http = await stack.enter_async_context(
                        httpx.AsyncClient(follow_redirects=False)
                    )
                    key = self.settings.deepseek_api_key
                    assert key is not None
                    model = await stack.enter_async_context(
                        AsyncOpenAI(
                            api_key=key.get_secret_value(),
                            base_url=self.settings.deepseek_base_url,
                            timeout=self.settings.total_timeout_seconds,
                            max_retries=self.settings.max_retries,
                        )
                    )
                    ports = LivePorts(
                        search=PublicSearchPortAdapter(
                            PublicSearchClient(
                                http,
                                self.settings,
                                SearchBudget.start(self.settings),
                            )
                        ),
                        fetch=HttpxFetchAdapter(
                            http,
                            allow_proxy_dns=self.settings.allow_proxy_dns,
                            user_agent=self.settings.user_agent,
                            max_retries=self.settings.max_retries,
                        ),
                        model=OpenAICompatibleModelAdapter(
                            model,
                            provider="openai-compatible",
                            default_model=self.settings.model,
                            thinking_enabled=self.settings.model_thinking_enabled,
                        ),
                    )
                async with asyncio.timeout(self.settings.total_timeout_seconds):
                    outcome = await self._orchestrator(run_id, ports).run(run_id)
                    await self._report(
                        run_id,
                        ReportType.FULL_INVESTIGATION
                        if outcome.termination == "READY_FOR_REPORT"
                        else ReportType.INVESTIGATION_STATUS,
                    )
                    self._finish(
                        run_id,
                        RunStatus(outcome.termination),
                        None if outcome.termination == "READY_FOR_REPORT" else outcome.reason,
                    )
        except asyncio.CancelledError:
            self._finish(
                run_id,
                RunStatus.INTERRUPTED if self._closing else RunStatus.CANCELLED,
                "SERVER_SHUTDOWN" if self._closing else "USER_CANCELLED",
            )
            raise
        except Exception as error:
            # Provider exceptions can embed credentials or response bodies. Persist only type/code.
            reason = "RUN_TIMEOUT" if isinstance(error, TimeoutError) else type(error).__name__
            self._finish(run_id, RunStatus.FAILED, f"{reason}: inspect configuration and retry")
            LOGGER.warning("Live run %s failed (%s)", run_id, reason)
            try:
                await self._report(run_id, ReportType.INVESTIGATION_STATUS)
            except Exception as report_error:
                LOGGER.warning(
                    "Status report for %s failed (%s)", run_id, type(report_error).__name__
                )

    def _finish(self, run_id: str, status: RunStatus, reason: str | None) -> None:
        with self.sessions.begin() as session:
            row = session.get(InvestigationRunRow, run_id)
            if row is not None:
                row.status = status
                row.interruption_reason = reason
                row.updated_at = datetime.now(UTC)
                row.completed_at = row.updated_at
                row.owner_instance_id = None
                row.owner_heartbeat_at = None

    async def _report(self, run_id: str, report_type: ReportType) -> None:
        await ReportPipeline(self.sessions, self.repository, DeterministicWriter()).generate(
            run_id=run_id,
            report_type=report_type,
            now=datetime.now(UTC),
        )

    def _orchestrator(self, run_id: str, ports: LivePorts) -> AgentFeedbackOrchestrator:
        integrity = EvidenceIntegrityValidator(
            blobs=self.blobs,
            recognized_versions=RecognizedArtifactVersions(
                snapshot_parsers=frozenset(
                    {
                        ("html", "1", "text-normalizer-v1"),
                        ("plain-text", "1", "text-normalizer-v1"),
                        ("pypdf-text-layer", "1", "text-normalizer-v1"),
                    }
                ),
                artifact_processors=frozenset(
                    {
                        ("html", "1"),
                        ("plain-text", "1"),
                        ("pypdf-text-layer", "1"),
                    }
                ),
            ),
        )
        return AgentFeedbackOrchestrator(
            harness=InvestigationHarness(HarnessStore(self.sessions, self.repository), self.blobs),
            calls=BoundExternalCalls(
                sessions=self.sessions,
                repository=self.repository,
                recordings=RepositoryRecordedCallStore(self.repository, self.blobs),
                live_search=ports.search,
                live_fetch=ports.fetch,
                live_model=ports.model,
            ),
            store=FeedbackStore(self.sessions, self.repository),
            repository=self.repository,
            blobs=self.blobs,
            parsers=DocumentParserRegistry.default(),
            validation_policy=ValidationPolicy(integrity=integrity),
            integrity=integrity,
            owner_instance_id=f"live-{run_id}",
            progress=lambda name, status: self.worker_activity.setdefault(run_id, {}).__setitem__(
                name, status
            ),
            config=FeedbackLoopConfig(
                ground_model_quotes=True,
                workflow_version="parallel-research-v2",
                research_workers=self.settings.research_workers,
                search_concurrency=self.settings.max_search_concurrency,
                fetch_concurrency=self.settings.max_fetch_concurrency,
                queries_per_researcher=self.settings.max_queries_per_researcher,
                step_timeout_seconds=min(600, self.settings.total_timeout_seconds),
                max_artifacts=30,
                max_excerpts=60,
                max_context_chars=100_000,
                max_verification_evidence=200,
            ),
        )
