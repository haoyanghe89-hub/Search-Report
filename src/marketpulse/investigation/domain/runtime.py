from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from marketpulse.investigation.domain.base import DomainModel, EntityId, NonEmptyText, Sha256
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    ResearchTaskStatus,
    RunMode,
    RunStatus,
    StepType,
    WorkflowPhase,
)


class InvestigationScope(DomainModel):
    summary: NonEmptyText
    inclusions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    geographic_scope: tuple[str, ...] = ()
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def valid_time_window(self) -> InvestigationScope:
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("scope end cannot precede scope start")
        return self


class InvestigationQuestion(DomainModel):
    question_id: EntityId
    text: NonEmptyText
    is_critical: bool = False


class Investigation(DomainModel):
    investigation_id: EntityId
    title: NonEmptyText
    event_description: NonEmptyText
    investigation_goal: NonEmptyText
    scope: InvestigationScope
    questions: tuple[InvestigationQuestion, ...] = ()
    critical_question_ids: tuple[EntityId, ...] = ()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def questions_are_consistent(self) -> Investigation:
        question_ids = [question.question_id for question in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("investigation question ids must be unique")
        unknown = set(self.critical_question_ids) - set(question_ids)
        if unknown:
            raise ValueError(f"unknown critical question ids: {sorted(unknown)}")
        marked = {question.question_id for question in self.questions if question.is_critical}
        if marked != set(self.critical_question_ids):
            raise ValueError("critical question projection must match question flags")
        return self


class InvestigationRun(DomainModel):
    run_id: EntityId
    investigation_id: EntityId
    mode: RunMode
    status: RunStatus
    current_phase: WorkflowPhase
    checkpoint_version: int = Field(ge=0)
    state_version: int = Field(ge=0)
    workflow_version: NonEmptyText
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None
    interruption_reason: str | None = None


class ExecutionStep(DomainModel):
    step_id: EntityId
    run_id: EntityId
    step_type: StepType
    agent_role: AgentRole
    status: ExecutionStepStatus
    attempt: int = Field(ge=1)
    input_fingerprint: Sha256
    output_refs: tuple[str, ...] = ()
    executor_instance_id: str | None = None
    started_at: datetime | None = None
    heartbeat_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    retryable: bool = False


class ResearchTask(DomainModel):
    task_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    target_question_id: EntityId | None = None
    title: NonEmptyText
    objective: NonEmptyText
    status: ResearchTaskStatus
    priority: int = Field(ge=0, le=100)
    query_hints: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
