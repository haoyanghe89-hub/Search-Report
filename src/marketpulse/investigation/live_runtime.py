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
from sqlalchemy import and_, or_, select
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
from marketpulse.investigation.recovery import (
    WORKFLOW_VERSION,
    RecoveryConflict,
    ResumeRequest,
    RunRecovery,
    live_feedback_config,
)
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
        self.recovery = RunRecovery(
            sessions,
            repository,
            self.blobs,
            settings,
            restore_quarantine=(blob_root / ".restore-quarantine.json").exists(),
        )
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self._closing = False
        self._stalled: set[str] = set()
        self.worker_activity: dict[str, dict[str, str]] = {}

    def recover_interrupted(self) -> None:
        """Single-worker API: abandoned jobs must not look like running work forever."""
        with self.sessions.begin() as session:
            rows = session.scalars(
                select(InvestigationRunRow).where(
                    InvestigationRunRow.mode == RunMode.LIVE,
                    or_(
                        InvestigationRunRow.status.in_(_ACTIVE),
                        and_(
                            InvestigationRunRow.status == RunStatus.READY_FOR_REPORT,
                            InvestigationRunRow.completed_at.is_(None),
                        ),
                    ),
                )
            ).all()
            for row in rows:
                row.status = RunStatus.INTERRUPTED
                row.state_version += 1
                row.interruption_reason = "SERVER_RESTARTED: inspect recovery options"
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

    def _ensure_available(self) -> None:
        if self._closing:
            raise LiveNotConfiguredError("服务正在关闭，请稍后重试。")
        key = self.settings.deepseek_api_key
        if self.ports is None and (key is None or not key.get_secret_value().strip()):
            raise LiveNotConfiguredError(
                "实时调查需要模型凭据：请配置 DEEPSEEK_API_KEY 后重启服务；"
                "DEEPSEEK_BASE_URL 和 MARKETPULSE_MODEL 可用于兼容的模型服务。"
            )

    def start(self, investigation_id: str) -> str:
        self._ensure_available()
        self.repository.get(Investigation, investigation_id)
        run_id = f"RUN-LIVE-{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)
        run = InvestigationRun(
            run_id=run_id,
            investigation_id=investigation_id,
            mode=RunMode.LIVE,
            status=RunStatus.CREATED,
            current_phase=WorkflowPhase.CREATED,
            checkpoint_version=0,
            state_version=0,
            workflow_version=WORKFLOW_VERSION,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        budget = RunBudget(
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
        with self.sessions.begin() as session:
            for entity in (run, budget, self.recovery.config_event(run_id, investigation_id)):
                self.repository.add_in_session(session, entity)
        self._schedule(run_id)
        return run_id

    def resume(self, run_id: str, request: ResumeRequest, *, automatic: bool = False) -> None:
        self._ensure_available()
        task = self.tasks.get(run_id)
        if task is not None and not task.done():
            raise RecoveryConflict("RUN_STILL_ACTIVE", "任务仍在执行，请等待停止后恢复。")
        authorized = self.recovery.prepare(
            run_id,
            request,
            automatic=automatic,
            max_auto_attempts=self.settings.auto_resume_max_attempts,
            backoff_seconds=self.settings.auto_resume_backoff_seconds,
        )
        self._schedule(run_id, authorized)

    def _schedule(self, run_id: str, authorized: frozenset[str] = frozenset()) -> None:
        self.worker_activity[run_id] = {}
        task = asyncio.create_task(self._execute(run_id, authorized), name=run_id)
        self.tasks[run_id] = task

        def cleanup(completed: asyncio.Task[None]) -> None:
            if self.tasks.get(run_id) is completed:
                self.tasks.pop(run_id, None)
                self.worker_activity.pop(run_id, None)
                self._stalled.discard(run_id)

        task.add_done_callback(cleanup)

    async def cancel(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        if task is None or task.done():
            return False
        # Persist the user's stop intent before waiting, including a process-kill window.
        with self.sessions.begin() as session:
            row = session.get(InvestigationRunRow, run_id)
            if row is not None:
                row.status = RunStatus.CANCELLED
                row.interruption_reason = "USER_CANCELLED"
                row.state_version += 1
                row.updated_at = datetime.now(UTC)
                row.completed_at = row.updated_at
                # Keep ownership until the cancelled step records its final checkpoint.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self._finish(run_id, RunStatus.CANCELLED, "USER_CANCELLED")
        return True

    async def interrupt_stalled(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        self._stalled.add(run_id)
        if task is not None and not task.done():
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=5)
            if not done:
                return False
        current = self.repository.get(InvestigationRun, run_id)
        if (
            current.status is RunStatus.CANCELLED
            and current.interruption_reason == "USER_CANCELLED"
        ):
            # Cancellation initiated by the watchdog uses a distinct reason below.
            return True
        self._finish(run_id, RunStatus.INTERRUPTED, "WATCHDOG_STALLED")
        return True

    async def shutdown(self) -> None:
        self._closing = True
        pending = tuple((run_id, task) for run_id, task in self.tasks.items() if not task.done())
        for _, task in pending:
            task.cancel()
        await asyncio.gather(*(task for _, task in pending), return_exceptions=True)
        for run_id, _ in pending:
            self._finish(run_id, RunStatus.INTERRUPTED, "SERVER_SHUTDOWN: inspect recovery options")

    async def _execute(self, run_id: str, authorized: frozenset[str] = frozenset()) -> None:
        try:
            run = self.repository.get(InvestigationRun, run_id)
            if run.current_phase is WorkflowPhase.REPORT:
                # Report regeneration is local and does not need external-call budget.
                async with asyncio.timeout(30):
                    await self._report(
                        run_id,
                        ReportType.FULL_INVESTIGATION
                        if run.status is RunStatus.READY_FOR_REPORT
                        else ReportType.INVESTIGATION_STATUS,
                    )
                self._finish(run_id, run.status, run.interruption_reason)
                return
            budget = HarnessStore(self.sessions, self.repository).read_budget(run_id)
            remaining_seconds = max(
                0.001, (budget.max_wall_time_ms - budget.consumed_wall_time_ms) / 1000
            )
            search_settings = self.settings.model_copy(
                update={
                    "total_timeout_seconds": remaining_seconds,
                    "max_search_queries": max(
                        0, budget.max_search_calls - budget.search_calls_used
                    ),
                    "max_pages": max(0, budget.max_fetch_calls - budget.fetch_calls_used),
                }
            )
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
                            # Avoid hidden SDK retries after ambiguous provider outcomes.
                            max_retries=0,
                        )
                    )
                    ports = LivePorts(
                        search=PublicSearchPortAdapter(
                            PublicSearchClient(
                                http,
                                self.settings,
                                SearchBudget.start(search_settings),
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
                async with asyncio.timeout(remaining_seconds):
                    outcome = await self._orchestrator(run_id, ports, authorized).run(run_id)
                    await self._report(
                        run_id,
                        ReportType.FULL_INVESTIGATION
                        if outcome.termination == "READY_FOR_REPORT"
                        else ReportType.INVESTIGATION_STATUS,
                    )
                    self._finish(
                        run_id,
                        RunStatus(outcome.termination),
                        None
                        if outcome.termination == "READY_FOR_REPORT"
                        else outcome.summary.termination_reason,
                    )
        except asyncio.CancelledError:
            self._finish(
                run_id,
                RunStatus.INTERRUPTED
                if self._closing or run_id in self._stalled
                else RunStatus.CANCELLED,
                "SERVER_SHUTDOWN"
                if self._closing
                else "WATCHDOG_STALLED"
                if run_id in self._stalled
                else "USER_CANCELLED",
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
                if (
                    row.status is RunStatus.CANCELLED
                    and row.interruption_reason == "USER_CANCELLED"
                    and status is not RunStatus.CANCELLED
                ):
                    return
                row.status = status
                row.state_version += 1
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

    def _orchestrator(
        self,
        run_id: str,
        ports: LivePorts,
        authorized: frozenset[str] = frozenset(),
    ) -> AgentFeedbackOrchestrator:
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
                authorized_unknown_intent_ids=authorized,
                pause_on_unknown_outcome=True,
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
            config=live_feedback_config(self.settings),
        )
