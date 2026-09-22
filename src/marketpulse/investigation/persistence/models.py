from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from marketpulse.investigation.domain.enums import (
    AgentRole,
    ArtifactType,
    AuditActorType,
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    ExecutionStepStatus,
    ExternalCallStatus,
    FindingSeverity,
    GapSeverity,
    GapStatus,
    LineageOriginType,
    LineageResolutionMethod,
    LocatorType,
    ParseStatus,
    RelationStance,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ReportValidatorKind,
    ResearchGapType,
    ResearchTaskStatus,
    ReviewDecisionOrigin,
    ReviewDecisionType,
    RunMode,
    RunStatus,
    SemanticJudgmentStatus,
    SourceType,
    StepType,
    TimePrecision,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.persistence.base import Base

ID = String(128)
HASH = String(64)
BLOB_REF = String(96)
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=max(len(member.value) for member in enum),
    )


class InvestigationRow(Base):
    __tablename__ = "inv_investigations"

    investigation_id: Mapped[str] = mapped_column(ID, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    investigation_goal: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvestigationQuestionRow(Base):
    __tablename__ = "inv_investigation_questions"
    __table_args__ = (
        Index("ix_inv_questions_investigation_critical", "investigation_id", "is_critical"),
    )

    question_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class InvestigationRunRow(Base):
    __tablename__ = "inv_runs"
    __table_args__ = (
        CheckConstraint("checkpoint_version >= 0", name="ck_inv_runs_checkpoint_nonnegative"),
        CheckConstraint("state_version >= 0", name="ck_inv_runs_state_nonnegative"),
        Index("ix_inv_runs_investigation_status", "investigation_id", "status"),
        Index("ix_inv_runs_phase_status", "current_phase", "status"),
    )

    run_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    mode: Mapped[RunMode] = mapped_column(enum_type(RunMode, "inv_run_mode"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_type(RunStatus, "inv_run_status"), nullable=False
    )
    current_phase: Mapped[WorkflowPhase] = mapped_column(
        enum_type(WorkflowPhase, "inv_workflow_phase"), nullable=False
    )
    checkpoint_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interruption_reason: Mapped[str | None] = mapped_column(Text)
    current_step_key: Mapped[str | None] = mapped_column(String(256))
    last_completed_step_key: Mapped[str | None] = mapped_column(String(256))
    owner_instance_id: Mapped[str | None] = mapped_column(String(128))
    owner_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin_run_id: Mapped[str | None] = mapped_column(String(128))
    origin_review_request_id: Mapped[str | None] = mapped_column(String(128))


class ExecutionStepRow(Base):
    __tablename__ = "inv_execution_steps"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_inv_steps_attempt_positive"),
        UniqueConstraint("run_id", "logical_step_key", "attempt", name="uq_inv_step_attempt"),
        Index("ix_inv_steps_run_status", "run_id", "status"),
        Index("ix_inv_steps_executor_heartbeat", "executor_instance_id", "heartbeat_at"),
    )

    step_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    step_type: Mapped[StepType] = mapped_column(
        enum_type(StepType, "inv_step_type"), nullable=False
    )
    agent_role: Mapped[AgentRole] = mapped_column(
        enum_type(AgentRole, "inv_agent_role"), nullable=False
    )
    status: Mapped[ExecutionStepStatus] = mapped_column(
        enum_type(ExecutionStepStatus, "inv_step_status"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False, index=True)
    output_refs: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    executor_instance_id: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    logical_step_key: Mapped[str] = mapped_column(String(256), nullable=False)
    dependency_keys: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    output_schema_version: Mapped[str | None] = mapped_column(String(100))
    active_elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RunBudgetRow(Base):
    __tablename__ = "inv_run_budgets"
    __table_args__ = (
        CheckConstraint("consumed_wall_time_ms >= 0", name="ck_inv_budget_wall_nonnegative"),
        CheckConstraint("sources_used >= 0", name="ck_inv_budget_sources_nonnegative"),
        CheckConstraint("sources_used <= max_sources", name="ck_inv_budget_sources_limit"),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    max_research_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_search_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_fetch_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_wall_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_sources: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    research_rounds_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetch_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consumed_wall_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sources_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CallBindingRow(Base):
    __tablename__ = "inv_call_bindings"
    __table_args__ = (
        CheckConstraint("call_ordinal >= 0", name="ck_inv_call_binding_ordinal"),
        UniqueConstraint(
            "run_id",
            "logical_step_key",
            "call_site_key",
            "call_ordinal",
            name="uq_inv_call_binding_site",
        ),
        Index("ix_inv_call_bindings_fingerprint", "request_fingerprint"),
        Index("ix_inv_call_bindings_recorded_call", "recorded_call_id"),
    )

    binding_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    logical_step_key: Mapped[str] = mapped_column(String(256), nullable=False)
    call_site_key: Mapped[str] = mapped_column(String(256), nullable=False)
    call_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    recorded_call_id: Mapped[str] = mapped_column(ID, nullable=False)
    call_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchTaskRow(Base):
    __tablename__ = "inv_research_tasks"
    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_inv_task_priority"),
        CheckConstraint("round >= 1", name="ck_inv_task_round_positive"),
        Index("ix_inv_tasks_run_status_priority", "run_id", "status", "priority"),
        Index("ix_inv_tasks_origin_gap", "origin_gap_id"),
        Index("ix_inv_tasks_target_claim", "target_claim_id"),
    )

    task_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    target_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_investigation_questions.question_id", ondelete="SET NULL")
    )
    target_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="SET NULL")
    )
    origin_gap_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_research_gaps.gap_id", ondelete="SET NULL")
    )
    parent_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_research_tasks.task_id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ResearchTaskStatus] = mapped_column(
        enum_type(ResearchTaskStatus, "inv_research_task_status"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    query_hints: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    preferred_source_types: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    suggested_queries: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceRow(Base):
    __tablename__ = "inv_sources"
    __table_args__ = (
        UniqueConstraint("investigation_id", "canonical_url", name="uq_inv_source_url"),
        Index("ix_inv_sources_canonical_url", "canonical_url"),
        Index("ix_inv_sources_origin", "origin_source_id"),
        Index("ix_inv_sources_syndication", "syndication_cluster_id"),
    )

    source_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(500))
    organization: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[SourceType] = mapped_column(
        enum_type(SourceType, "inv_source_type"), nullable=False
    )
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_first_hand: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_sources.source_id", ondelete="SET NULL")
    )
    syndication_cluster_id: Mapped[str | None] = mapped_column(String(128))


class SourceSnapshotRow(Base):
    __tablename__ = "inv_source_snapshots"
    __table_args__ = (
        CheckConstraint("content_size >= 0", name="ck_inv_snapshot_size_nonnegative"),
        CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_inv_snapshot_http_status",
        ),
        CheckConstraint("raw_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_snapshot_raw_blob_ref"),
        CheckConstraint("length(raw_sha256) = 64", name="ck_inv_snapshot_raw_hash"),
        CheckConstraint(
            "(cleaned_blob_ref IS NULL AND cleaned_sha256 IS NULL) OR "
            "(cleaned_blob_ref LIKE 'blob://sha256/%' AND length(cleaned_sha256) = 64)",
            name="ck_inv_snapshot_cleaned_pair",
        ),
        Index("ix_inv_snapshots_source_retrieved", "source_id", "retrieved_at"),
        Index("ix_inv_snapshots_run", "run_id"),
        Index("ix_inv_snapshots_raw_blob", "raw_blob_ref"),
        Index("ix_inv_snapshots_raw_hash", "raw_sha256"),
        Index("ix_inv_snapshots_cleaned_blob", "cleaned_blob_ref"),
        Index("ix_inv_snapshots_cleaned_hash", "cleaned_sha256"),
    )

    snapshot_id: Mapped[str] = mapped_column(ID, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("inv_sources.source_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(HASH, nullable=False)
    cleaned_blob_ref: Mapped[str | None] = mapped_column(BLOB_REF)
    cleaned_sha256: Mapped[str | None] = mapped_column(HASH)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    encoding: Mapped[str | None] = mapped_column(String(100))
    content_size: Mapped[int] = mapped_column(Integer, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[ParseStatus] = mapped_column(
        enum_type(ParseStatus, "inv_parse_status"), nullable=False
    )
    parser_name: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)


class DocumentArtifactRow(Base):
    __tablename__ = "inv_document_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", "snapshot_id", name="uq_inv_artifact_snapshot"),
        CheckConstraint("blob_ref LIKE 'blob://sha256/%'", name="ck_inv_artifact_blob_ref"),
        CheckConstraint("length(sha256) = 64", name="ck_inv_artifact_hash"),
        CheckConstraint("page_number IS NULL OR page_number >= 1", name="ck_inv_artifact_page"),
        Index("ix_inv_artifacts_snapshot_type", "snapshot_id", "artifact_type"),
        Index("ix_inv_artifacts_blob", "blob_ref"),
        Index("ix_inv_artifacts_hash", "sha256"),
    )

    artifact_id: Mapped[str] = mapped_column(ID, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("inv_source_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        enum_type(ArtifactType, "inv_artifact_type"), nullable=False
    )
    blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    sha256: Mapped[str] = mapped_column(HASH, nullable=False)
    processor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    processor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRow(Base):
    __tablename__ = "inv_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id", "snapshot_id"],
            ["inv_document_artifacts.artifact_id", "inv_document_artifacts.snapshot_id"],
            name="fk_inv_evidence_artifact_snapshot",
            ondelete="RESTRICT",
        ),
        CheckConstraint("length(content_hash) = 64", name="ck_inv_evidence_content_hash"),
        Index("ix_inv_evidence_run", "run_id"),
        Index("ix_inv_evidence_snapshot", "snapshot_id"),
        Index("ix_inv_evidence_artifact", "artifact_id"),
        Index("ix_inv_evidence_content_hash", "content_hash"),
        Index("ix_inv_evidence_created_step", "created_by_step_id"),
        Index("ix_inv_evidence_task", "research_task_id"),
    )

    evidence_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("inv_source_snapshots.snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_id: Mapped[str | None] = mapped_column(ID)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    locator_type: Mapped[LocatorType] = mapped_column(
        enum_type(LocatorType, "inv_locator_type"), nullable=False
    )
    locator_payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by_step_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_execution_steps.step_id", ondelete="SET NULL")
    )
    research_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_research_tasks.task_id", ondelete="SET NULL")
    )


class ClaimRow(Base):
    __tablename__ = "inv_claims"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_inv_claim_confidence",
        ),
        Index("ix_inv_claims_investigation_run", "investigation_id", "run_id"),
        Index("ix_inv_claims_type_status", "claim_type", "validation_status"),
        Index("ix_inv_claims_critical_status", "is_critical", "validation_status"),
        Index("ix_inv_claims_latest_validation", "latest_validation_id"),
        Index("ix_inv_claims_created_step", "created_by_step_id"),
        Index("ix_inv_claims_task", "research_task_id"),
    )

    claim_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[ClaimType] = mapped_column(
        enum_type(ClaimType, "inv_claim_type"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(Text)
    predicate: Mapped[str | None] = mapped_column(Text)
    object: Mapped[str | None] = mapped_column(Text)
    qualifiers: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    importance: Mapped[ClaimImportance] = mapped_column(
        enum_type(ClaimImportance, "inv_claim_importance"), nullable=False
    )
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_type(ValidationStatus, "inv_validation_status"), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_basis: Mapped[str | None] = mapped_column(Text)
    latest_validation_id: Mapped[str | None] = mapped_column(ID)
    created_by_step_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_execution_steps.step_id", ondelete="SET NULL")
    )
    research_task_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "inv_research_tasks.task_id",
            name="fk_inv_claims_task",
            ondelete="SET NULL",
            use_alter=True,
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaimEvidenceRelationRow(Base):
    __tablename__ = "inv_claim_evidence_relations"
    __table_args__ = (
        UniqueConstraint("claim_id", "evidence_id", name="uq_inv_claim_evidence_pair"),
        CheckConstraint(
            "entailment_score IS NULL OR (entailment_score >= 0 AND entailment_score <= 1)",
            name="ck_inv_relation_entailment_score",
        ),
        Index("ix_inv_relations_claim_stance", "claim_id", "stance"),
        Index("ix_inv_relations_evidence", "evidence_id"),
    )

    relation_id: Mapped[str] = mapped_column(ID, primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("inv_evidence.evidence_id", ondelete="RESTRICT"), nullable=False
    )
    stance: Mapped[RelationStance] = mapped_column(
        enum_type(RelationStance, "inv_relation_stance"), nullable=False
    )
    entailment_status: Mapped[EntailmentStatus] = mapped_column(
        enum_type(EntailmentStatus, "inv_entailment_status"), nullable=False
    )
    entailment_score: Mapped[float | None] = mapped_column(Float)
    semantic_judgment_ref: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConflictSetRow(Base):
    __tablename__ = "inv_conflict_sets"
    __table_args__ = (
        Index("ix_inv_conflicts_investigation_status", "investigation_id", "status"),
        Index("ix_inv_conflicts_run_severity", "run_id", "severity"),
        Index("ix_inv_conflicts_resolution", "resolution_status"),
    )

    conflict_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    conflict_type: Mapped[ConflictType] = mapped_column(
        enum_type(ConflictType, "inv_conflict_type"), nullable=False
    )
    severity: Mapped[ConflictSeverity] = mapped_column(
        enum_type(ConflictSeverity, "inv_conflict_severity"), nullable=False
    )
    status: Mapped[ConflictStatus] = mapped_column(
        enum_type(ConflictStatus, "inv_conflict_status"), nullable=False
    )
    possible_causes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    competing_values: Mapped[list[object]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    possible_explanations: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    resolution_status: Mapped[ConflictResolutionStatus] = mapped_column(String(40), nullable=False)
    resolution_basis: Mapped[str | None] = mapped_column(Text)
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConflictClaimRow(Base):
    __tablename__ = "inv_conflict_claims"

    conflict_id: Mapped[str] = mapped_column(
        ForeignKey("inv_conflict_sets.conflict_id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), primary_key=True
    )


class ConflictEvidenceRow(Base):
    __tablename__ = "inv_conflict_evidence"
    __table_args__ = (Index("ix_inv_conflict_evidence_evidence", "evidence_id"),)

    conflict_id: Mapped[str] = mapped_column(
        ForeignKey("inv_conflict_sets.conflict_id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("inv_evidence.evidence_id", ondelete="RESTRICT"), primary_key=True
    )


class ValidationResultRow(Base):
    __tablename__ = "inv_validation_results"
    __table_args__ = (
        CheckConstraint("independent_source_count >= 0", name="ck_inv_validation_independence"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inv_validation_confidence"),
        Index("ix_inv_validation_claim_created", "claim_id", "created_at"),
        Index("ix_inv_validation_run_status", "run_id", "status"),
        Index("ix_inv_validation_input_fingerprint", "input_fingerprint"),
        Index("ix_inv_validation_evidence_set_hash", "evidence_set_hash"),
        Index("ix_inv_validation_policy", "policy_version", "profile_version"),
    )

    validation_id: Mapped[str] = mapped_column(ID, primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    claim_type: Mapped[ClaimType] = mapped_column(
        enum_type(ClaimType, "inv_validation_claim_type"), nullable=False
    )
    profile_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    evidence_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    lineage_version: Mapped[str] = mapped_column(String(100), nullable=False)
    conflict_set_refs: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    citation_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    entailment_result: Mapped[EntailmentStatus] = mapped_column(
        enum_type(EntailmentStatus, "inv_validation_entailment"), nullable=False
    )
    independent_source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    strong_contradiction: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_quality_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    sufficiency_result: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ValidationStatus] = mapped_column(
        enum_type(ValidationStatus, "inv_validation_result_status"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validation_basis: Mapped[str] = mapped_column(Text, nullable=False)
    validation_basis_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    confidence_basis: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchGapRow(Base):
    __tablename__ = "inv_research_gaps"
    __table_args__ = (
        Index("ix_inv_gaps_run_status", "run_id", "status"),
        Index("ix_inv_gaps_investigation_severity", "investigation_id", "severity"),
        Index("ix_inv_gaps_claim_type", "target_claim_id", "gap_type"),
        Index("ix_inv_gaps_origin_validation", "origin_validation_id"),
        CheckConstraint(
            "gap_type IN ('EVIDENCE_GAP', 'UNREADABLE_SOURCE', 'SOURCE_CONFLICT', "
            "'MISSING_PRIMARY_SOURCE', 'INSUFFICIENT_INDEPENDENCE', "
            "'INSUFFICIENT_ENTAILMENT', 'MISSING_CAUSAL_SUPPORT', "
            "'MISSING_MECHANISM', 'UNRESOLVED_QUANTITATIVE_CONFLICT', "
            "'ATTRIBUTION_UNDER_SUPPORTED', 'ANALYSIS_ERROR', 'OTHER')",
            name="ck_inv_gap_type_values",
        ),
    )

    gap_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    gap_type: Mapped[ResearchGapType] = mapped_column(String(64), nullable=False)
    target_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_investigation_questions.question_id", ondelete="SET NULL")
    )
    target_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="SET NULL")
    )
    origin_validation_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_validation_results.validation_id", ondelete="SET NULL")
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_sources.source_id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_source_type: Mapped[str | None] = mapped_column(String(100))
    missing_requirement: Mapped[str | None] = mapped_column(Text)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[GapSeverity] = mapped_column(
        enum_type(GapSeverity, "inv_gap_severity"), nullable=False
    )
    status: Mapped[GapStatus] = mapped_column(
        enum_type(GapStatus, "inv_gap_status"), nullable=False
    )
    suggested_actions: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SemanticJudgmentRow(Base):
    __tablename__ = "inv_semantic_judgments"
    __table_args__ = (
        Index("ix_inv_semantic_claim_evidence", "claim_id", "evidence_id", "created_at"),
        Index("ix_inv_semantic_run", "run_id"),
        CheckConstraint(
            "semantic_confidence >= 0 AND semantic_confidence <= 1",
            name="ck_inv_semantic_confidence",
        ),
    )

    judgment_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("inv_evidence.evidence_id", ondelete="RESTRICT"), nullable=False
    )
    judgment: Mapped[SemanticJudgmentStatus] = mapped_column(
        enum_type(SemanticJudgmentStatus, "inv_semantic_judgment_status"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_call_ref: Mapped[str | None] = mapped_column(String(255))
    recorded_judgment_ref: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceFamilyRow(Base):
    __tablename__ = "inv_source_families"
    __table_args__ = (
        UniqueConstraint("validation_id", "family_id", name="uq_inv_family_validation"),
        Index("ix_inv_families_run_family", "run_id", "family_id"),
        Index("ix_inv_families_validation", "validation_id"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inv_family_confidence"),
    )

    family_record_id: Mapped[str] = mapped_column(ID, primary_key=True)
    validation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_validation_results.validation_id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    family_id: Mapped[str] = mapped_column(ID, nullable=False)
    lineage_version: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_type: Mapped[LineageOriginType] = mapped_column(
        enum_type(LineageOriginType, "inv_lineage_origin_type"), nullable=False
    )
    independence_basis: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_method: Mapped[LineageResolutionMethod] = mapped_column(
        enum_type(LineageResolutionMethod, "inv_lineage_resolution_method"), nullable=False
    )


class SourceFamilyMemberRow(Base):
    __tablename__ = "inv_source_family_members"
    __table_args__ = (Index("ix_inv_family_members_source", "source_id"),)

    family_record_id: Mapped[str] = mapped_column(
        ForeignKey("inv_source_families.family_record_id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("inv_sources.source_id", ondelete="RESTRICT"), primary_key=True
    )


class ValidationConflictRow(Base):
    __tablename__ = "inv_validation_conflicts"
    __table_args__ = (Index("ix_inv_validation_conflicts_conflict", "conflict_id"),)

    validation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_validation_results.validation_id", ondelete="CASCADE"), primary_key=True
    )
    conflict_id: Mapped[str] = mapped_column(
        ForeignKey("inv_conflict_sets.conflict_id", ondelete="RESTRICT"), primary_key=True
    )


class TimelineEventRow(Base):
    __tablename__ = "inv_timeline_events"
    __table_args__ = (
        Index("ix_inv_timeline_investigation_time", "investigation_id", "event_time"),
    )

    timeline_event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_precision: Mapped[TimePrecision] = mapped_column(
        enum_type(TimePrecision, "inv_time_precision"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    related_entity_ids: Mapped[list[str]] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=list
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_type(ValidationStatus, "inv_timeline_validation_status"), nullable=False
    )


class TimelineEvidenceRow(Base):
    __tablename__ = "inv_timeline_evidence"

    timeline_event_id: Mapped[str] = mapped_column(
        ForeignKey("inv_timeline_events.timeline_event_id", ondelete="CASCADE"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("inv_evidence.evidence_id", ondelete="RESTRICT"), primary_key=True
    )


class ReportRow(Base):
    """Append-only report version; lifecycle state lives in ReportProjectionRow."""

    __tablename__ = "inv_reports"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_inv_report_version"),
        CheckConstraint("length(report_hash) = 64", name="ck_inv_report_hash"),
        CheckConstraint("length(claim_set_hash) = 64", name="ck_inv_report_claim_set_hash"),
        CheckConstraint("length(citation_set_hash) = 64", name="ck_inv_report_citation_set_hash"),
        UniqueConstraint("investigation_id", "version", name="uq_inv_report_version"),
        Index("ix_inv_reports_run", "run_id"),
        Index("ix_inv_reports_hash", "report_hash"),
        Index("ix_inv_reports_claim_set_hash", "claim_set_hash"),
        Index("ix_inv_reports_snapshot_hash", "report_input_snapshot_hash"),
    )

    report_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    report_type: Mapped[ReportType] = mapped_column(
        enum_type(ReportType, "inv_report_type"), nullable=False
    )
    report_input_snapshot_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    citation_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    release_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportSectionRow(Base):
    __tablename__ = "inv_report_sections"
    __table_args__ = (
        CheckConstraint("order_index >= 0", name="ck_inv_report_section_order"),
        CheckConstraint(
            "content_blob_ref IS NOT NULL OR structured_content IS NOT NULL",
            name="ck_inv_report_section_content",
        ),
        CheckConstraint(
            "content_blob_ref IS NULL OR content_blob_ref LIKE 'blob://sha256/%'",
            name="ck_inv_report_section_blob_ref",
        ),
        UniqueConstraint("report_id", "order_index", name="uq_inv_report_section_order"),
        Index("ix_inv_report_sections_report_type", "report_id", "section_type"),
        Index("ix_inv_report_sections_blob", "content_blob_ref"),
    )

    section_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="CASCADE"), nullable=False
    )
    section_type: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_blob_ref: Mapped[str | None] = mapped_column(BLOB_REF)
    structured_content: Mapped[dict[str, Any] | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportSectionClaimRow(Base):
    __tablename__ = "inv_report_section_claims"

    section_id: Mapped[str] = mapped_column(
        ForeignKey("inv_report_sections.section_id", ondelete="CASCADE"), primary_key=True
    )
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), primary_key=True
    )


class ReviewDecisionRow(Base):
    __tablename__ = "inv_review_decisions"
    __table_args__ = (
        CheckConstraint("report_version >= 1", name="ck_inv_review_report_version"),
        CheckConstraint("length(report_hash) = 64", name="ck_inv_review_report_hash"),
        CheckConstraint("length(claim_set_hash) = 64", name="ck_inv_review_claim_set_hash"),
        Index("ix_inv_reviews_report_created", "report_id", "created_at"),
    )

    review_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(ID, nullable=False)
    decision: Mapped[ReviewDecisionType] = mapped_column(
        enum_type(ReviewDecisionType, "inv_review_decision"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    release_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    review_request_id: Mapped[str | None] = mapped_column(String(128))
    reviewer_session_public_id: Mapped[str | None] = mapped_column(String(128))
    reviewer_config_fingerprint: Mapped[str | None] = mapped_column(HASH)
    decision_origin: Mapped[ReviewDecisionOrigin] = mapped_column(
        enum_type(ReviewDecisionOrigin, "inv_review_decision_origin"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "inv_audit_events"
    __table_args__ = (
        Index("ix_inv_audit_investigation_created", "investigation_id", "created_at"),
        Index("ix_inv_audit_target", "target_type", "target_id"),
    )

    audit_event_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(ForeignKey("inv_runs.run_id", ondelete="RESTRICT"))
    actor_type: Mapped[AuditActorType] = mapped_column(
        enum_type(AuditActorType, "inv_audit_actor_type"), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_id: Mapped[str] = mapped_column(ID, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(100))
    new_state: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecordedToolCallRow(Base):
    __tablename__ = "inv_recorded_tool_calls"
    __table_args__ = (
        CheckConstraint("request_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_tool_request_blob"),
        CheckConstraint(
            "response_blob_ref IS NULL OR response_blob_ref LIKE 'blob://sha256/%'",
            name="ck_inv_tool_response_blob",
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_inv_tool_request_hash"),
        CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_inv_tool_response_hash",
        ),
        CheckConstraint(
            "(response_blob_ref IS NULL) = (response_hash IS NULL)",
            name="ck_inv_tool_response_pair",
        ),
        CheckConstraint("attempt >= 1", name="ck_inv_tool_attempt_positive"),
        CheckConstraint(
            "replayable = false OR (status = 'SUCCESS' AND response_blob_ref IS NOT NULL)",
            name="ck_inv_tool_replayable_success",
        ),
        Index("ix_inv_tool_calls_step", "step_id"),
        Index("ix_inv_tool_calls_fingerprint", "request_fingerprint"),
        Index(
            "ix_inv_tool_calls_replay_lookup",
            "run_id",
            "operation",
            "request_fingerprint",
            "status",
            "replayable",
        ),
        Index("ix_inv_tool_calls_request_blob", "request_blob_ref"),
        Index("ix_inv_tool_calls_request_hash", "request_hash"),
        Index("ix_inv_tool_calls_response_blob", "response_blob_ref"),
        Index("ix_inv_tool_calls_response_hash", "response_hash"),
    )

    call_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("inv_execution_steps.step_id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    request_blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    response_blob_ref: Mapped[str | None] = mapped_column(BLOB_REF)
    response_hash: Mapped[str | None] = mapped_column(HASH)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExternalCallStatus] = mapped_column(
        enum_type(ExternalCallStatus, "inv_external_call_status"), nullable=False
    )
    replayable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecordedModelCallRow(Base):
    __tablename__ = "inv_recorded_model_calls"
    __table_args__ = (
        CheckConstraint(
            "request_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_model_request_blob"
        ),
        CheckConstraint(
            "response_blob_ref IS NULL OR response_blob_ref LIKE 'blob://sha256/%'",
            name="ck_inv_model_response_blob",
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_inv_model_request_hash"),
        CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_inv_model_response_hash",
        ),
        CheckConstraint(
            "(response_blob_ref IS NULL) = (response_hash IS NULL)",
            name="ck_inv_model_response_pair",
        ),
        CheckConstraint("attempt >= 1", name="ck_inv_model_attempt_positive"),
        CheckConstraint(
            "replayable = false OR (status = 'SUCCESS' AND response_blob_ref IS NOT NULL)",
            name="ck_inv_model_replayable_success",
        ),
        Index("ix_inv_model_calls_step", "step_id"),
        Index("ix_inv_model_calls_fingerprint", "request_fingerprint"),
        Index(
            "ix_inv_model_calls_replay_lookup",
            "run_id",
            "operation",
            "request_fingerprint",
            "status",
            "replayable",
        ),
        Index("ix_inv_model_calls_request_blob", "request_blob_ref"),
        Index("ix_inv_model_calls_request_hash", "request_hash"),
        Index("ix_inv_model_calls_response_blob", "response_blob_ref"),
        Index("ix_inv_model_calls_response_hash", "response_hash"),
    )

    call_id: Mapped[str] = mapped_column(ID, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("inv_execution_steps.step_id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    request_blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    request_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    response_blob_ref: Mapped[str | None] = mapped_column(BLOB_REF)
    response_hash: Mapped[str | None] = mapped_column(HASH)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExternalCallStatus] = mapped_column(
        enum_type(ExternalCallStatus, "inv_external_call_status"), nullable=False
    )
    replayable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportInputSnapshotRow(Base):
    __tablename__ = "inv_report_input_snapshots"
    __table_args__ = (
        CheckConstraint("length(snapshot_hash) = 64", name="ck_inv_ris_snapshot_hash"),
        CheckConstraint("length(claim_set_hash) = 64", name="ck_inv_ris_claim_set_hash"),
        CheckConstraint(
            "length(source_state_fingerprint) = 64", name="ck_inv_ris_source_fingerprint"
        ),
        UniqueConstraint("snapshot_hash", name="uq_inv_ris_snapshot_hash"),
        Index("ix_inv_ris_run", "run_id"),
        Index("ix_inv_ris_claim_set_hash", "claim_set_hash"),
    )

    snapshot_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    run_mode: Mapped[RunMode] = mapped_column(enum_type(RunMode, "inv_run_mode"), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    source_state_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    semantic_payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    runtime_references: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    assembled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportProjectionRow(Base):
    """Controlled-mutable latest lifecycle projection for a report version."""

    __tablename__ = "inv_report_projections"

    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="CASCADE"), primary_key=True
    )
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    review_status: Mapped[ReportReviewStatus] = mapped_column(
        enum_type(ReportReviewStatus, "inv_report_review_status"), nullable=False
    )
    release_status: Mapped[ReportReleaseStatus] = mapped_column(
        enum_type(ReportReleaseStatus, "inv_report_release_status"), nullable=False
    )
    active_review_request_id: Mapped[str | None] = mapped_column(String(128))
    latest_evaluation_id: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CitationRow(Base):
    __tablename__ = "inv_citations"
    __table_args__ = (
        CheckConstraint("display_ordinal >= 0", name="ck_inv_citations_ordinal"),
        CheckConstraint("length(citation_hash) = 64", name="ck_inv_citations_hash"),
        UniqueConstraint("report_id", "citation_hash", name="uq_inv_citations_report_hash"),
        Index("ix_inv_citations_hash", "citation_hash"),
        Index("ix_inv_citations_report_section", "report_id", "section_key"),
        Index("ix_inv_citations_claim", "claim_id"),
        Index("ix_inv_citations_evidence", "evidence_id"),
    )

    citation_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    display_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="RESTRICT"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("inv_evidence.evidence_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_input_snapshot_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_key: Mapped[str] = mapped_column(String(200), nullable=False)
    claim_semantic_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    validation_semantic_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    relation_semantics: Mapped[str] = mapped_column(String(200), nullable=False)
    evidence_semantic_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    canonical_locator: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    resolved_quote_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    artifact_content_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    snapshot_content_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    source_semantic_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    entailment_judgment: Mapped[str] = mapped_column(String(100), nullable=False)
    entailment_version: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    citation_hash: Mapped[str] = mapped_column(HASH, nullable=False)


class ReportValidationFindingRow(Base):
    __tablename__ = "inv_report_validation_findings"
    __table_args__ = (Index("ix_inv_rvf_report_severity", "report_id", "severity"),)

    finding_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    validator: Mapped[ReportValidatorKind] = mapped_column(
        enum_type(ReportValidatorKind, "inv_report_validator_kind"), nullable=False
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        enum_type(FindingSeverity, "inv_finding_severity"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    section_key: Mapped[str | None] = mapped_column(String(100))
    unit_key: Mapped[str | None] = mapped_column(String(200))
    claim_stable_key: Mapped[str | None] = mapped_column(String(200))
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReleasePolicyEvaluationRow(Base):
    __tablename__ = "inv_release_policy_evaluations"
    __table_args__ = (
        CheckConstraint("hard_finding_count >= 0", name="ck_inv_rpe_hard_count"),
        CheckConstraint("governance_finding_count >= 0", name="ck_inv_rpe_governance_count"),
        UniqueConstraint("report_id", "evaluation_hash", name="uq_inv_rpe_report_hash"),
        Index("ix_inv_rpe_report", "report_id"),
    )

    evaluation_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[ReleaseDecision] = mapped_column(
        enum_type(ReleaseDecision, "inv_release_decision"), nullable=False
    )
    release_status: Mapped[ReportReleaseStatus] = mapped_column(
        enum_type(ReportReleaseStatus, "inv_report_release_status"), nullable=False
    )
    review_status: Mapped[ReportReviewStatus] = mapped_column(
        enum_type(ReportReviewStatus, "inv_report_review_status"), nullable=False
    )
    evaluation_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    citation_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    hard_finding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_finding_count: Mapped[int] = mapped_column(Integer, nullable=False)
    basis: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRequestRow(Base):
    __tablename__ = "inv_review_requests"
    __table_args__ = (
        CheckConstraint("report_version >= 1", name="ck_inv_rrq_report_version"),
        Index("ix_inv_rrq_report_created", "report_id", "created_at"),
        Index("ix_inv_rrq_evaluation", "evaluation_hash"),
    )

    request_id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    citation_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_release_policy_evaluations.evaluation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewerSessionRow(Base):
    __tablename__ = "inv_reviewer_sessions"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="ck_inv_reviewer_sessions_generation"),
        UniqueConstraint("token_hash", name="uq_inv_reviewer_sessions_token_hash"),
        Index("ix_inv_reviewer_sessions_reviewer", "reviewer_id"),
    )

    session_public_id: Mapped[str] = mapped_column(ID, primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    reviewer_config_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewerAuthStateRow(Base):
    __tablename__ = "inv_reviewer_auth_state"

    reviewer_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    active_session_public_id: Mapped[str | None] = mapped_column(String(128))
    active_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRateBucketRow(Base):
    __tablename__ = "inv_reviewer_rate_buckets"

    bucket_fingerprint: Mapped[str] = mapped_column(HASH, primary_key=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewResearchRequestRow(Base):
    __tablename__ = "inv_review_research_requests"
    __table_args__ = (Index("ix_inv_rrr_report", "report_id"),)

    request_id: Mapped[str] = mapped_column(ID, primary_key=True)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("inv_review_decisions.review_id", ondelete="RESTRICT"), nullable=False
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewIdempotencyRow(Base):
    __tablename__ = "inv_review_idempotency"
    __table_args__ = (Index("ix_inv_review_idempotency_report", "report_id"),)

    idempotency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    report_id: Mapped[str] = mapped_column(
        ForeignKey("inv_reports.report_id", ondelete="RESTRICT"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[ReviewDecisionType] = mapped_column(
        enum_type(ReviewDecisionType, "inv_review_decision"), nullable=False
    )
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecordedHumanReviewDecisionRow(Base):
    __tablename__ = "inv_recorded_human_review_decisions"
    __table_args__ = (UniqueConstraint("semantic_fingerprint", name="uq_inv_rhrd_fingerprint"),)

    recorded_id: Mapped[str] = mapped_column(ID, primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[ReviewDecisionType] = mapped_column(
        enum_type(ReviewDecisionType, "inv_review_decision"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    citation_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    release_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evaluation_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(HASH, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
