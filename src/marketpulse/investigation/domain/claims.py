from __future__ import annotations

from datetime import datetime

from pydantic import Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    Confidence,
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    GapSeverity,
    GapStatus,
    RelationStance,
    ResearchGapType,
    SourceType,
    TimePrecision,
    ValidationStatus,
)


class Claim(DomainModel):
    claim_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    statement: NonEmptyText
    claim_type: ClaimType
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    importance: ClaimImportance
    is_critical: bool = False
    validation_status: ValidationStatus = ValidationStatus.PENDING
    confidence: Confidence | None = None
    confidence_basis: str | None = None
    latest_validation_id: EntityId | None = None
    created_by_step_id: EntityId | None = None
    research_task_id: EntityId | None = None
    created_at: datetime
    updated_at: datetime


class ClaimEvidenceRelation(DomainModel):
    relation_id: EntityId
    claim_id: EntityId
    evidence_id: EntityId
    stance: RelationStance
    entailment_status: EntailmentStatus
    entailment_score: Confidence | None = None
    semantic_judgment_ref: str | None = None
    created_at: datetime


class ConflictSet(DomainModel):
    conflict_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    claim_ids: tuple[EntityId, ...]
    conflict_type: ConflictType
    severity: ConflictSeverity
    status: ConflictStatus
    evidence_ids: tuple[EntityId, ...] = ()
    possible_causes: tuple[str, ...] = ()
    competing_values: tuple[JsonValue, ...] = ()
    possible_explanations: tuple[str, ...] = ()
    resolution_status: ConflictResolutionStatus = ConflictResolutionStatus.UNRESOLVED
    resolution_basis: str | None = None
    resolution_summary: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def has_distinct_references(self) -> ConflictSet:
        if not self.claim_ids:
            raise ValueError("conflict set requires at least one claim")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("conflict set claim ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("conflict set evidence ids must be unique")
        return self


class ValidationResult(DomainModel):
    validation_id: EntityId
    claim_id: EntityId
    run_id: EntityId
    claim_type: ClaimType
    profile_version: NonEmptyText
    policy_version: NonEmptyText = "legacy-policy"
    input_fingerprint: Sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
    evidence_set_hash: Sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
    lineage_version: NonEmptyText = "legacy-lineage"
    conflict_set_refs: tuple[EntityId, ...] = ()
    citation_valid: bool
    entailment_result: EntailmentStatus
    independent_source_count: int = Field(ge=0)
    strong_contradiction: bool
    source_quality_summary: dict[str, JsonValue] = Field(default_factory=dict)
    sufficiency_result: NonEmptyText
    status: ValidationStatus
    confidence: Confidence
    validation_basis: NonEmptyText
    validation_basis_payload: dict[str, JsonValue] = Field(default_factory=dict)
    confidence_basis: NonEmptyText = "Legacy confidence basis"
    created_at: datetime


class ResearchGap(DomainModel):
    gap_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    gap_type: ResearchGapType
    target_question_id: EntityId | None = None
    target_claim_id: EntityId | None = None
    origin_validation_id: EntityId | None = None
    source_id: EntityId | None = None
    reason: NonEmptyText
    preferred_source_type: SourceType | None = None
    missing_requirement: str | None = None
    suggested_action: str | None = None
    severity: GapSeverity
    status: GapStatus
    suggested_actions: tuple[str, ...] = ()
    created_at: datetime
    resolved_at: datetime | None = None


class TimelineEvent(DomainModel):
    timeline_event_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    event_time: datetime | None = None
    time_precision: TimePrecision
    description: NonEmptyText
    related_entity_ids: tuple[EntityId, ...] = ()
    supporting_evidence_ids: tuple[EntityId, ...] = ()
    validation_status: ValidationStatus
