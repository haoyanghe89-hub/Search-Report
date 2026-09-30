"""Explicit same-run recovery; audit-backed checkpoints, consent and additive budgets."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.config import Settings
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.agents.prompts import PROMPT_VERSION
from marketpulse.investigation.domain.enums import (
    AuditActorType,
    ExecutionStepStatus,
    ExternalCallStatus,
    GapStatus,
    ResearchTaskStatus,
    RunMode,
    RunStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.feedback.models import FeedbackLoopConfig
from marketpulse.investigation.persistence.models import (
    AuditEventRow,
    ExecutionStepRow,
    InvestigationRunRow,
    RecordedModelCallRow,
    ResearchGapRow,
    ResearchTaskRow,
    RunBudgetRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository

WORKFLOW_VERSION = "resumable-retrieval-v4"


def live_feedback_config(settings: Settings) -> FeedbackLoopConfig:
    return FeedbackLoopConfig(
        ground_model_quotes=True,
        workflow_version=WORKFLOW_VERSION,
        retrieval_strategy="bm25-passages-v1",
        research_workers=settings.research_workers,
        search_concurrency=settings.max_search_concurrency,
        fetch_concurrency=settings.max_fetch_concurrency,
        queries_per_researcher=settings.max_queries_per_researcher,
        step_timeout_seconds=min(600, settings.total_timeout_seconds),
        max_artifacts=30,
        max_excerpts=60,
        max_context_chars=100_000,
        max_verification_evidence=200,
    )


def execution_profile(settings: Settings) -> str:
    # Budget limits and credentials can change. Inputs, model and execution semantics cannot.
    fields = (
        "model",
        "deepseek_base_url",
        "model_thinking_enabled",
        "page_timeout_seconds",
        "max_page_bytes",
        "allow_proxy_dns",
        "max_retries",
        "user_agent",
        "search_user_agent",
    )
    config = live_feedback_config(settings).model_dump(exclude={"step_timeout_seconds"})
    payload = {
        "settings": {k: getattr(settings, k) for k in fields},
        "workflow": config,
        "prompt_version": PROMPT_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class RecoveryConflict(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class BudgetIncrease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search_calls: int = Field(default=0, ge=0, le=1000, strict=True)
    fetch_calls: int = Field(default=0, ge=0, le=2000, strict=True)
    model_calls: int = Field(default=0, ge=0, le=2000, strict=True)
    tokens: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    wall_time_ms: int = Field(default=0, ge=0, le=7_200_000, strict=True)
    sources: int = Field(default=0, ge=0, le=2000, strict=True)
    research_rounds: int = Field(default=0, ge=0, le=20, strict=True)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_state_version: int = Field(ge=0, strict=True)
    retry_unknown_intent_ids: list[str] = Field(default_factory=list, max_length=2000)
    budget_increase: BudgetIncrease = Field(default_factory=BudgetIncrease)


_BUDGETS = {
    "search_calls": ("search_calls_used", 1000),
    "fetch_calls": ("fetch_calls_used", 2000),
    "model_calls": ("model_calls_used", 2000),
    "tokens": ("tokens_used", 10_000_000),
    "wall_time_ms": ("consumed_wall_time_ms", 7_200_000),
    "sources": ("sources_used", 2000),
    "research_rounds": ("research_rounds_used", 20),
}
_STOPPED = {RunStatus.INTERRUPTED, RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.BLOCKED}


def unknown_model_calls(session: Session, run_id: str) -> list[dict[str, Any]]:
    intents = session.scalars(
        select(AuditEventRow).where(
            AuditEventRow.run_id == run_id,
            AuditEventRow.event_type == "MODEL_CALL_INTENT",
        )
    ).all()
    records = session.scalars(
        select(RecordedModelCallRow).where(
            RecordedModelCallRow.run_id == run_id,
        )
    ).all()
    latest: dict[str, AuditEventRow] = {}
    for intent in intents:
        previous = latest.get(intent.target_id)
        if previous is None or int(intent.metadata_payload["sequence"]) > int(
            previous.metadata_payload["sequence"]
        ):
            latest[intent.target_id] = intent
    unknown = []
    for intent in latest.values():
        m = intent.metadata_payload
        terminal = next(
            (
                r
                for r in records
                if r.request_fingerprint == m["request_fingerprint"]
                and r.attempt == m["record_attempt"]
                and all(
                    r.metadata_payload.get(k) == m[k]
                    for k in ("logical_step_key", "call_site_key", "call_ordinal")
                )
            ),
            None,
        )
        if terminal is None or terminal.status in {
            ExternalCallStatus.TIMEOUT,
            ExternalCallStatus.CANCELLED,
            ExternalCallStatus.PROVIDER_ERROR,
        }:
            unknown.append(
                {
                    "intent_id": intent.audit_event_id,
                    "logical_step_key": m["logical_step_key"],
                    "call_site_key": m["call_site_key"],
                }
            )
    return sorted(unknown, key=lambda item: item["intent_id"])


class RunRecovery:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        blobs: BlobStoragePort,
        settings: Settings,
        *,
        restore_quarantine: bool = False,
    ) -> None:
        self.sessions, self.repository, self.blobs = sessions, repository, blobs
        self.profile = execution_profile(settings)
        self.restore_quarantine = restore_quarantine

    def config_event(self, run_id: str, investigation_id: str) -> AuditEvent:
        return AuditEvent(
            audit_event_id=f"RUN-CONFIG-{run_id}",
            investigation_id=investigation_id,
            run_id=run_id,
            actor_type=AuditActorType.SYSTEM,
            event_type="RUN_EXECUTION_CONFIG",
            target_type="InvestigationRun",
            target_id=run_id,
            metadata={"workflow_version": WORKFLOW_VERSION, "profile_hash": self.profile},
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _pause(session: Session, run: InvestigationRunRow) -> AuditEventRow | None:
        events = session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.run_id == run.run_id,
                AuditEventRow.event_type == "RUN_BUDGET_BLOCKED",
            )
        ).all()
        return next(
            (
                e
                for e in events
                if e.metadata_payload.get("blocking_step_key") == run.last_completed_step_key
            ),
            None,
        )

    @staticmethod
    def _terminal(session: Session, run: InvestigationRunRow) -> RunStatus | None:
        events = session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.run_id == run.run_id,
                AuditEventRow.event_type == "RUN_REPORT_READY",
            )
        ).all()
        event = next(
            (
                e
                for e in events
                if e.metadata_payload.get("logical_step_key") == run.last_completed_step_key
            ),
            None,
        )
        if event and event.metadata_payload.get("status") in {"READY_FOR_REPORT", "BLOCKED"}:
            return RunStatus(event.metadata_payload["status"])
        return None

    def _inspect(self, session: Session, run: InvestigationRunRow) -> dict[str, Any]:
        budget = session.get(RunBudgetRow, run.run_id)
        result: dict[str, Any] = {
            "can_resume": False,
            "reason": None,
            "state_version": run.state_version,
            "unknown_calls": [],
            "budget": {
                k: getattr(budget, k)
                for name, (used, _) in _BUDGETS.items()
                for k in (f"max_{name}", used)
            }
            if budget
            else None,
        }
        reason = None
        if self.restore_quarantine:
            reason = (
                "此数据库由历史备份恢复，可能缺少备份后已计费的调用。"
                "请先核对供应商记录，再由运维解除恢复隔离。"
            )
        elif run.mode is not RunMode.LIVE:
            reason = "回放任务不能通过恢复接口转为联网运行。"
        elif run.workflow_version != WORKFLOW_VERSION:
            reason = "旧版本缺少兼容的恢复检查点，请使用对应版本或另建运行。"
        elif run.status not in _STOPPED:
            reason = "仅可恢复已中断、已取消、可重试失败或预算不足的任务。"
        elif run.owner_instance_id is not None:
            reason = "任务仍由执行器持有，请等待运行停止。"
        elif budget is None:
            reason = "缺少原运行预算，无法安全恢复。"
        config = session.get(AuditEventRow, f"RUN-CONFIG-{run.run_id}")
        if reason is None and (
            config is None or config.metadata_payload.get("profile_hash") != self.profile
        ):
            reason = "模型或执行配置与原运行不一致，请恢复原配置后继续。"
        pause = self._pause(session, run)
        if reason is None and run.status is RunStatus.BLOCKED and pause is None:
            reason = "该任务因证据或验证问题停止，不能通过追加预算自动重启。"
        if (
            reason is None
            and run.current_phase is WorkflowPhase.REPORT
            and pause is None
            and self._terminal(session, run) is None
        ):
            reason = "缺少报告阶段的完成记录，无法安全恢复。"
        if reason is None:
            from marketpulse.investigation.harness.checkpoints import validate_saved_input

            checkpoints = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run.run_id,
                    AuditEventRow.event_type == "STEP_INPUT_SAVED",
                )
            ).all()
            steps = session.scalars(
                select(ExecutionStepRow).where(
                    ExecutionStepRow.run_id == run.run_id,
                )
            ).all()
            saved_keys = {e.metadata_payload.get("logical_step_key") for e in checkpoints}
            try:
                for event in checkpoints:
                    validate_saved_input(
                        self.repository.get_in_session(session, AuditEvent, event.audit_event_id),
                        self.blobs,
                    )
                    if event.metadata_payload.get("workflow_version") != WORKFLOW_VERSION:
                        raise ValueError("checkpoint version mismatch")
                for step in steps:
                    if step.step_type in {
                        StepType.PLANNING,
                        StepType.RESEARCH,
                        StepType.ANALYSIS,
                        StepType.VALIDATION,
                    }:
                        if step.logical_step_key not in saved_keys:
                            raise ValueError("missing input")
                    if step.step_type is StepType.VALIDATION:
                        if f"{step.logical_step_key}:workers" not in saved_keys:
                            raise ValueError("missing verification partition")
                    if step.step_type is StepType.RESEARCH and step.logical_step_key:
                        round_number = step.logical_step_key.rsplit("-", 1)[-1]
                        if f"round:before:{round_number}" not in saved_keys:
                            raise ValueError("missing round baseline")
                    if step.status is ExecutionStepStatus.COMPLETED:
                        for uri in step.output_refs:
                            from marketpulse.infrastructure.storage.models import BlobRef

                            self.blobs.get_bytes(BlobRef.from_uri(uri))
            except (ValueError, RuntimeError, OSError, KeyError):
                reason = "恢复检查点缺失、损坏或版本不兼容，已阻止恢复。"
            if reason is None and run.current_step_key:
                current = max(
                    (s for s in steps if s.logical_step_key == run.current_step_key),
                    key=lambda s: s.attempt,
                    default=None,
                )
                if (
                    current
                    and current.status is ExecutionStepStatus.FAILED
                    and not current.retryable
                ):
                    if current.error_code not in {
                        "MODEL_CALL_OUTCOME_UNKNOWN",
                        "RunBudgetExceededError",
                        "RUN_BUDGET_EXCEEDED",
                    }:
                        reason = "该步骤失败不可重试，需先处理失败原因。"
        result["can_resume"] = reason is None
        result["reason"] = reason
        if reason is None:
            result["unknown_calls"] = unknown_model_calls(session, run.run_id)
        return result

    def inspect(self, run_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            run = session.get(InvestigationRunRow, run_id)
            if run is None:
                raise KeyError(run_id)
            return self._inspect(session, run)

    def prepare(
        self,
        run_id: str,
        request: ResumeRequest,
        *,
        automatic: bool = False,
        max_auto_attempts: int = 3,
        backoff_seconds: float = 15,
    ) -> frozenset[str]:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            run = session.get(InvestigationRunRow, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.state_version != request.expected_state_version:
                raise RecoveryConflict("STALE_RUN_STATE", "任务状态已变化，请刷新后重新确认。")
            if automatic:
                if run.status not in {RunStatus.INTERRUPTED, RunStatus.FAILED}:
                    raise RecoveryConflict("AUTO_RESUME_INELIGIBLE", "该运行需要手动处理。")
                if request.retry_unknown_intent_ids or any(
                    request.budget_increase.model_dump().values()
                ):
                    raise RecoveryConflict(
                        "AUTO_RESUME_UNSAFE", "自动恢复不能授权未知调用或追加预算。"
                    )
                attempts = session.scalars(
                    select(AuditEventRow).where(
                        AuditEventRow.run_id == run_id,
                        AuditEventRow.event_type == "RUN_RESUMED",
                    )
                ).all()
                automatic_attempts = [a for a in attempts if a.metadata_payload.get("automatic")]
                if len(automatic_attempts) >= max_auto_attempts:
                    raise RecoveryConflict(
                        "AUTO_RESUME_LIMIT", "自动恢复次数已达上限，请检查后手动继续。"
                    )
                last = max(
                    (a.created_at for a in automatic_attempts),
                    default=run.completed_at or run.updated_at,
                )
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                if run.completed_at is not None:
                    completed = run.completed_at
                    if completed.tzinfo is None:
                        completed = completed.replace(tzinfo=UTC)
                    last = max(last, completed)
                delay = min(3600, backoff_seconds * 2 ** len(automatic_attempts))
                if (now - last).total_seconds() < delay:
                    raise RecoveryConflict("AUTO_RESUME_BACKOFF", "正在等待自动恢复退避时间。")
            info = self._inspect(session, run)
            if not info["can_resume"]:
                raise RecoveryConflict("RUN_NOT_RESUMABLE", info["reason"])
            unknown = frozenset(c["intent_id"] for c in info["unknown_calls"])
            if frozenset(request.retry_unknown_intent_ids) != unknown:
                raise RecoveryConflict(
                    "UNKNOWN_CALL_CONSENT_REQUIRED",
                    "存在执行结果不明的调用，请逐项确认可能重复费用后重试。",
                )
            budget = session.get(RunBudgetRow, run_id)
            assert budget is not None
            limits: dict[str, int] = {}
            for name, (_, cap) in _BUDGETS.items():
                total = getattr(budget, f"max_{name}") + getattr(request.budget_increase, name)
                if total > cap:
                    raise RecoveryConflict(
                        "BUDGET_LIMIT_EXCEEDED", f"{name} 累计上限不能超过 {cap}。"
                    )
                limits[f"max_{name}"] = total
            pause = self._pause(session, run)
            phase = (
                WorkflowPhase(pause.metadata_payload["resume_phase"])
                if pause
                else run.current_phase
            )
            step_key = (
                pause.metadata_payload.get("resume_step_key") if pause else run.current_step_key
            )
            required = (
                ["model_calls", "tokens", "wall_time_ms"]
                if phase is not WorkflowPhase.REPORT
                else []
            )
            if phase is WorkflowPhase.COLLECT:
                required.extend(["search_calls", "fetch_calls", "sources"])
            if phase is WorkflowPhase.COLLECT:
                tasks = session.scalars(
                    select(ResearchTaskRow).where(
                        ResearchTaskRow.run_id == run_id,
                        ResearchTaskRow.status == ResearchTaskStatus.PENDING,
                    )
                ).all()
                if tasks:
                    needed_round = max(t.round for t in tasks)
                elif step_key and step_key.startswith("planning:feedback:round-"):
                    needed_round = int(step_key.rsplit("-", 1)[-1])
                else:
                    needed_round = budget.research_rounds_used + 1
                if needed_round > limits["max_research_rounds"]:
                    raise RecoveryConflict(
                        "BUDGET_INCREASE_REQUIRED", "研究轮次已耗尽，请追加额度。"
                    )
            for name in required:
                if getattr(budget, _BUDGETS[name][0]) >= limits[f"max_{name}"]:
                    raise RecoveryConflict(
                        "BUDGET_INCREASE_REQUIRED", f"{name} 已耗尽，请追加额度。"
                    )
            result = session.execute(
                update(InvestigationRunRow)
                .where(
                    InvestigationRunRow.run_id == run_id,
                    InvestigationRunRow.state_version == request.expected_state_version,
                    InvestigationRunRow.status == run.status,
                    InvestigationRunRow.owner_instance_id.is_(None),
                )
                .values(
                    status=(
                        self._terminal(session, run)
                        if phase is WorkflowPhase.REPORT
                        else RunStatus.PENDING
                    ),
                    current_phase=phase,
                    current_step_key=step_key,
                    state_version=run.state_version + 1,
                    completed_at=None,
                    interruption_reason=None,
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise RecoveryConflict("STALE_RUN_STATE", "其他请求已恢复该任务，请刷新。")
            for key, value in limits.items():
                setattr(budget, key, value)
            budget.updated_at = now
            if step_key:
                step = session.scalar(
                    select(ExecutionStepRow)
                    .where(
                        ExecutionStepRow.run_id == run_id,
                        ExecutionStepRow.logical_step_key == step_key,
                    )
                    .order_by(ExecutionStepRow.attempt.desc())
                )
                if step and step.status is not ExecutionStepStatus.COMPLETED:
                    step.status = ExecutionStepStatus.INTERRUPTED
                    step.retryable = True
            if pause:
                # Only the synthetic stop marker is resolved; substantive evidence gaps stay open.
                for gap in session.scalars(
                    select(ResearchGapRow).where(
                        ResearchGapRow.run_id == run_id,
                        ResearchGapRow.status == GapStatus.OPEN,
                        ResearchGapRow.gap_id.in_(pause.metadata_payload.get("gap_ids", [])),
                    )
                ):
                    gap.status = GapStatus.RESOLVED
                    gap.resolved_at = now
            self.repository.add_in_session(
                session,
                AuditEvent(
                    audit_event_id=f"RESUME-{uuid.uuid4().hex}",
                    investigation_id=run.investigation_id,
                    run_id=run_id,
                    actor_type=AuditActorType.SYSTEM if automatic else AuditActorType.HUMAN,
                    event_type="RUN_RESUMED",
                    target_type="InvestigationRun",
                    target_id=run_id,
                    metadata={
                        "automatic": automatic,
                        "expected_state_version": request.expected_state_version,
                        "authorized_unknown_intent_ids": sorted(unknown),
                        "budget_increase": request.budget_increase.model_dump(mode="json"),
                        "resume_phase": phase.value,
                    },
                    created_at=now,
                ),
            )
        return unknown
