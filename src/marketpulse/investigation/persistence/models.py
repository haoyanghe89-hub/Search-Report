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
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    ExecutionStepStatus,
    GapSeverity,
    GapStatus,
    LocatorType,
    ParseStatus,
    RelationStance,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ResearchGapType,
    ResearchTaskStatus,
    ReviewDecisionType,
    RunMode,
    RunStatus,
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


class ExecutionStepRow(Base):
    __tablename__ = "inv_execution_steps"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="ck_inv_steps_attempt_positive"),
        UniqueConstraint("run_id", "input_fingerprint", "attempt", name="uq_inv_step_attempt"),
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


class ResearchTaskRow(Base):
    __tablename__ = "inv_research_tasks"
    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 100", name="ck_inv_task_priority"),
        Index("ix_inv_tasks_run_status_priority", "run_id", "status", "priority"),
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
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ResearchTaskStatus] = mapped_column(
        enum_type(ResearchTaskStatus, "inv_research_task_status"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    query_hints: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
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


class ValidationResultRow(Base):
    __tablename__ = "inv_validation_results"
    __table_args__ = (
        CheckConstraint("independent_source_count >= 0", name="ck_inv_validation_independence"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inv_validation_confidence"),
        Index("ix_inv_validation_claim_created", "claim_id", "created_at"),
        Index("ix_inv_validation_run_status", "run_id", "status"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchGapRow(Base):
    __tablename__ = "inv_research_gaps"
    __table_args__ = (
        Index("ix_inv_gaps_run_status", "run_id", "status"),
        Index("ix_inv_gaps_investigation_severity", "investigation_id", "severity"),
    )

    gap_id: Mapped[str] = mapped_column(ID, primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("inv_investigations.investigation_id", ondelete="RESTRICT"), nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("inv_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    gap_type: Mapped[ResearchGapType] = mapped_column(
        enum_type(ResearchGapType, "inv_gap_type"), nullable=False
    )
    target_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_investigation_questions.question_id", ondelete="SET NULL")
    )
    target_claim_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_claims.claim_id", ondelete="SET NULL")
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("inv_sources.source_id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
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
    __tablename__ = "inv_reports"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_inv_report_version"),
        CheckConstraint("length(report_hash) = 64", name="ck_inv_report_hash"),
        CheckConstraint("length(claim_set_hash) = 64", name="ck_inv_report_claim_set_hash"),
        UniqueConstraint("investigation_id", "version", name="uq_inv_report_version"),
        Index("ix_inv_reports_run_release", "run_id", "release_status"),
        Index("ix_inv_reports_hash", "report_hash"),
        Index("ix_inv_reports_claim_set_hash", "claim_set_hash"),
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
    review_status: Mapped[ReportReviewStatus] = mapped_column(
        enum_type(ReportReviewStatus, "inv_report_review_status"), nullable=False
    )
    release_status: Mapped[ReportReleaseStatus] = mapped_column(
        enum_type(ReportReleaseStatus, "inv_report_release_status"), nullable=False
    )
    report_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    release_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
            "response_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_tool_response_blob"
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_inv_tool_request_hash"),
        CheckConstraint("length(response_hash) = 64", name="ck_inv_tool_response_hash"),
        UniqueConstraint(
            "run_id", "operation", "request_fingerprint", name="uq_inv_tool_call_fingerprint"
        ),
        Index("ix_inv_tool_calls_step", "step_id"),
        Index("ix_inv_tool_calls_fingerprint", "request_fingerprint"),
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
    response_blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    response_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecordedModelCallRow(Base):
    __tablename__ = "inv_recorded_model_calls"
    __table_args__ = (
        CheckConstraint(
            "request_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_model_request_blob"
        ),
        CheckConstraint(
            "response_blob_ref LIKE 'blob://sha256/%'", name="ck_inv_model_response_blob"
        ),
        CheckConstraint("length(request_hash) = 64", name="ck_inv_model_request_hash"),
        CheckConstraint("length(response_hash) = 64", name="ck_inv_model_response_hash"),
        UniqueConstraint(
            "run_id", "operation", "request_fingerprint", name="uq_inv_model_call_fingerprint"
        ),
        Index("ix_inv_model_calls_step", "step_id"),
        Index("ix_inv_model_calls_fingerprint", "request_fingerprint"),
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
    response_blob_ref: Mapped[str] = mapped_column(BLOB_REF, nullable=False)
    response_hash: Mapped[str] = mapped_column(HASH, nullable=False)
    provider: Mapped[str] = mapped_column(String(200), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, nullable=False, default=dict
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
