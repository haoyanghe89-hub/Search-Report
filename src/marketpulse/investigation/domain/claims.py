from __future__ import annotations

from datetime import datetime

from pydantic import Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    Confidence,
    DomainModel,
    EntityId,
    NonEmptyText,
)
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    GapSeverity,
    GapStatus,
    RelationStance,
    ResearchGapType,
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
    possible_causes: tuple[str, ...] = ()
    resolution_summary: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def has_distinct_claims(self) -> ConflictSet:
        if not self.claim_ids:
            raise ValueError("conflict set requires at least one claim")
        if len(self.claim_ids) != len(set(self.claim_ids)):
            raise ValueError("conflict set claim ids must be unique")
        return self


class ValidationResult(DomainModel):
    validation_id: EntityId
    claim_id: EntityId
    run_id: EntityId
    claim_type: ClaimType
    profile_version: NonEmptyText
    citation_valid: bool
    entailment_result: EntailmentStatus
    independent_source_count: int = Field(ge=0)
    strong_contradiction: bool
    source_quality_summary: dict[str, JsonValue] = Field(default_factory=dict)
    sufficiency_result: NonEmptyText
    status: ValidationStatus
    confidence: Confidence
    validation_basis: NonEmptyText
    created_at: datetime


class ResearchGap(DomainModel):
    gap_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    gap_type: ResearchGapType
    target_question_id: EntityId | None = None
    target_claim_id: EntityId | None = None
    source_id: EntityId | None = None
    reason: NonEmptyText
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
