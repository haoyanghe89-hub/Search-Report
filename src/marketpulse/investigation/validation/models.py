from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    Confidence,
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
    ResearchGap,
    ValidationResult,
)
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictType,
    ImpactSubtype,
    LineageOriginType,
    LineageResolutionMethod,
    QualityLevel,
    SemanticJudgmentStatus,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)


class IntegrityErrorCode(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    MISSING_SNAPSHOT = "MISSING_SNAPSHOT"
    MISSING_ARTIFACT = "MISSING_ARTIFACT"
    INVALID_LOCATOR = "INVALID_LOCATOR"
    LOCATOR_OUT_OF_RANGE = "LOCATOR_OUT_OF_RANGE"
    QUOTE_MISMATCH = "QUOTE_MISMATCH"
    BLOB_NOT_FOUND = "BLOB_NOT_FOUND"
    BLOB_INTEGRITY_ERROR = "BLOB_INTEGRITY_ERROR"
    SNAPSHOT_ARTIFACT_MISMATCH = "SNAPSHOT_ARTIFACT_MISMATCH"
    UNRECOGNIZED_VERSION = "UNRECOGNIZED_VERSION"


class IntegrityFailure(DomainModel):
    code: IntegrityErrorCode
    detail: NonEmptyText


class EvidenceIntegrityResult(DomainModel):
    evidence_id: EntityId
    valid: bool
    snapshot_id: EntityId | None = None
    artifact_id: EntityId | None = None
    resolved_excerpt: str | None = None
    failures: tuple[IntegrityFailure, ...] = ()

    @model_validator(mode="after")
    def result_is_consistent(self) -> EvidenceIntegrityResult:
        if self.valid == bool(self.failures):
            raise ValueError("valid integrity results cannot have failures")
        return self


class RecognizedArtifactVersions(DomainModel):
    snapshot_parsers: frozenset[tuple[str, str, str]]
    artifact_processors: frozenset[tuple[str, str]]


class SemanticJudgment(DomainModel):
    judgment_id: EntityId
    run_id: EntityId
    claim_id: EntityId
    evidence_id: EntityId
    judgment: SemanticJudgmentStatus
    reason: NonEmptyText
    semantic_confidence: Confidence
    model_call_ref: str | None = None
    recorded_judgment_ref: str | None = None
    schema_version: NonEmptyText = "1"
    created_at: datetime


class AtomicityAssessment(DomainModel):
    is_atomic: bool
    issues: tuple[str, ...] = ()
    proposed_atomic_statements: tuple[str, ...] = ()


class ClaimNormalizationProposal(DomainModel):
    canonical_statement: NonEmptyText
    entity_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    time_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    scope_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    claim_type: ClaimType
    importance: ClaimImportance
    critical: bool = False
    atomicity: AtomicityAssessment


class ClaimNormalizationResult(DomainModel):
    accepted: bool
    canonical_statement: NonEmptyText
    qualifiers: dict[str, JsonValue]
    claim_type: ClaimType
    importance: ClaimImportance
    critical: bool
    atomicity: AtomicityAssessment
    rejection_reasons: tuple[str, ...] = ()


class SourceAttribution(DomainModel):
    source_id: EntityId
    attributed_source_id: EntityId
    basis: NonEmptyText


class SourceFamily(DomainModel):
    family_id: EntityId
    origin_type: LineageOriginType
    member_source_ids: tuple[EntityId, ...]
    independence_basis: tuple[str, ...]
    confidence: Confidence
    resolution_method: LineageResolutionMethod


class LineageResolution(DomainModel):
    version: NonEmptyText
    families: tuple[SourceFamily, ...]
    source_to_family: dict[str, str]


class IndependentEvidenceAssessment(DomainModel):
    source_count: int = Field(ge=0)
    independent_family_count: int = Field(ge=0)
    families: tuple[SourceFamily, ...]
    duplicate_or_syndicated_members: tuple[tuple[EntityId, ...], ...] = ()
    primary_family_count: int = Field(ge=0)
    secondary_independent_family_count: int = Field(ge=0)
    basis: tuple[str, ...]


class QualityComponent(DomainModel):
    name: NonEmptyText
    level: QualityLevel
    basis: NonEmptyText
    normalized_value: Confidence | None = None


class SourceQualityAssessment(DomainModel):
    source_id: EntityId
    family_id: EntityId
    components: tuple[QualityComponent, ...]
    basis: tuple[str, ...]
    normalized_score: Confidence | None = None

    def component(self, name: str) -> QualityComponent:
        for item in self.components:
            if item.name == name:
                return item
        raise KeyError(name)


class ConflictObservation(DomainModel):
    claim_id: EntityId
    evidence_id: EntityId
    statement: NonEmptyText
    conflict_type: ConflictType
    numeric_value: float | None = None
    unit: str | None = None
    report_time: datetime | None = None
    scope: str | None = None
    definition: str | None = None
    methodology: str | None = None
    report_stage: Literal["PRELIMINARY", "INTERIM", "FINAL", "UNKNOWN"] = "UNKNOWN"
    directness: Confidence = 0.5
    specificity: Confidence = 0.5


class ConflictDetectionResult(DomainModel):
    conflicts: tuple[ConflictSet, ...]
    compared_observations: int = Field(ge=0)


class StrongContradictionAssessment(DomainModel):
    triggered: bool
    evidence_ids: tuple[EntityId, ...] = ()
    basis: tuple[str, ...]


class ProfileSufficiency(DomainModel):
    profile: ClaimType
    profile_version: NonEmptyText
    sufficient: bool
    recommended_status: Literal["VERIFIED", "PROBABLE", "UNVERIFIED"]
    missing_requirements: tuple[str, ...] = ()
    gap_codes: tuple[str, ...] = ()
    basis: tuple[str, ...]
    special_semantic_checks: tuple[str, ...] = ()


class ValidationRequest(DomainModel):
    validation_id: EntityId
    created_at: datetime
    claim: Claim
    target_question_id: EntityId | None = None
    relations: tuple[ClaimEvidenceRelation, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    snapshots: tuple[SourceSnapshot, ...] = ()
    artifacts: tuple[DocumentArtifact, ...] = ()
    sources: tuple[Source, ...] = ()
    semantic_judgments: tuple[SemanticJudgment, ...] = ()
    explicit_attributions: tuple[SourceAttribution, ...] = ()
    conflict_observations: tuple[ConflictObservation, ...] = ()
    existing_conflicts: tuple[ConflictSet, ...] = ()


class ValidationOutcome(DomainModel):
    result: ValidationResult
    integrity_results: tuple[EvidenceIntegrityResult, ...]
    lineage: LineageResolution
    independence: IndependentEvidenceAssessment
    quality_assessments: tuple[SourceQualityAssessment, ...]
    conflict_updates: tuple[ConflictSet, ...]
    strong_contradiction: StrongContradictionAssessment
    research_gaps: tuple[ResearchGap, ...]
    pipeline_stages: tuple[str, ...]
    semantic_content_hash: Sha256


class ValidationBasis(DomainModel):
    profile: ClaimType
    profile_sufficient: bool
    integrity_valid_evidence_ids: tuple[EntityId, ...]
    integrity_failures: dict[str, tuple[str, ...]]
    semantic_judgments: dict[str, str]
    independent_family_count: int
    primary_family_count: int
    strong_contradiction: bool
    unresolved_conflict_ids: tuple[EntityId, ...]
    quality_scores: dict[str, float | None]
    impact_subtype: ImpactSubtype | None = None
    special_checks: tuple[str, ...] = ()
