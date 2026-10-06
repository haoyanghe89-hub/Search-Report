"""Phase 5.2 Writer: bounded projection, typed narrative units, structured drafts.

The Writer never reads repositories and never receives trusted URLs, locators,
quote hashes, blob references, or source metadata. It receives only a bounded
``WriterProjection`` derived from the immutable ``ReportInputSnapshot`` and
emits typed ``NarrativeUnit`` objects. Every factual unit must carry
``claim_refs``; evidence never bypasses claims.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from marketpulse.investigation.domain.base import DomainModel, NonEmptyText
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictSeverity,
    ConflictStatus,
    ReportType,
    TimePrecision,
    ValidationStatus,
)
from marketpulse.investigation.reporting.models import ReportInputSnapshot

WRITER_SCHEMA_VERSION = "phase5-writer-v1"


class ContentClass(StrEnum):
    FACTUAL_ASSERTION = "FACTUAL_ASSERTION"
    ANALYTICAL_SYNTHESIS = "ANALYTICAL_SYNTHESIS"
    GOVERNANCE_DISCLOSURE = "GOVERNANCE_DISCLOSURE"
    PRESENTATIONAL = "PRESENTATIONAL"


class SectionStatus(StrEnum):
    CONTENT = "CONTENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT_SUPPORTED_MATERIAL = "INSUFFICIENT_SUPPORTED_MATERIAL"


FULL_SECTIONS: tuple[str, ...] = (
    "EXECUTIVE_SUMMARY",
    "SCOPE_AND_MANDATE",
    "INVESTIGATION_QUESTIONS",
    "METHODOLOGY",
    "SOURCE_COVERAGE",
    "TIMELINE",
    "VERIFIED_FINDINGS",
    "PROBABLE_FINDINGS",
    "DISPUTED_FINDINGS",
    "QUANTITATIVE_FINDINGS",
    "IMPACT_SCOPE_AND_ANALYSIS",
    "CAUSAL_AND_MECHANISM_ANALYSIS",
    "ACTOR_AND_ATTRIBUTION_ASSESSMENT",
    "CONFLICT_ANALYSIS",
    "REMEDIATION_AND_FOLLOW_UP",
    "LIMITATIONS_AND_RESEARCH_GAPS",
    "CONCLUSIONS_AND_NEXT_STEPS",
)

STATUS_SECTIONS: tuple[str, ...] = (
    "EXECUTIVE_STATUS",
    "SCOPE_AND_MANDATE",
    "INVESTIGATION_QUESTIONS",
    "SEARCH_AND_SOURCE_SUMMARY",
    "AVAILABLE_FINDINGS",
    "BLOCKING_GAPS_AND_LIMITATIONS",
    "NEXT_STEPS",
)

COMPACT_FULL_SECTIONS: tuple[str, ...] = (
    "EXECUTIVE_SUMMARY",
    "CORE_FINDINGS",
    "EVIDENCE_BASE",
    "LIMITATIONS_AND_RESEARCH_GAPS",
    "RESEARCH_APPENDIX",
    "TECHNICAL_APPENDIX",
)

COMPACT_STATUS_SECTIONS: tuple[str, ...] = (
    "EXECUTIVE_STATUS",
    "CORE_FINDINGS",
    "EVIDENCE_BASE",
    "BLOCKING_GAPS_AND_LIMITATIONS",
    "RESEARCH_APPENDIX",
    "TECHNICAL_APPENDIX",
)


def required_sections(report_type: ReportType) -> tuple[str, ...]:
    if report_type is ReportType.INVESTIGATION_STATUS:
        return ("EXECUTIVE_STATUS", "EVIDENCE_BASE")
    return ("EXECUTIVE_SUMMARY", "EVIDENCE_BASE")


def allowed_sections(report_type: ReportType) -> tuple[str, ...]:
    """Accept compact drafts and legacy section keys during rolling upgrades."""
    if report_type is ReportType.INVESTIGATION_STATUS:
        return tuple(
            dict.fromkeys((*COMPACT_STATUS_SECTIONS, *STATUS_SECTIONS, "QUANTITATIVE_FINDINGS"))
        )
    return tuple(dict.fromkeys((*COMPACT_FULL_SECTIONS, *FULL_SECTIONS)))


class NarrativeUnit(DomainModel):
    unit_key: NonEmptyText
    section_key: NonEmptyText
    text: NonEmptyText
    content_class: ContentClass
    claim_refs: tuple[NonEmptyText, ...] = ()
    evidence_intents: tuple[NonEmptyText, ...] = ()


class DraftSection(DomainModel):
    section_key: NonEmptyText
    status: SectionStatus
    units: tuple[NarrativeUnit, ...] = ()


class ReportDraft(DomainModel):
    report_type: ReportType
    schema_version: NonEmptyText = WRITER_SCHEMA_VERSION
    sections: tuple[DraftSection, ...]


class ProjectionClaim(DomainModel):
    stable_key: NonEmptyText
    statement: NonEmptyText
    claim_type: ClaimType
    validation_status: ValidationStatus
    confidence: float
    importance: ClaimImportance
    is_critical: bool
    report_section: str | None = None
    supporting_relations: int = 0
    contradicting_relations: int = 0


class ProjectionConflict(DomainModel):
    stable_key: NonEmptyText
    conflict_type: NonEmptyText
    severity: ConflictSeverity
    status: ConflictStatus
    claim_refs: tuple[NonEmptyText, ...]
    resolution_summary: str | None = None
    possible_explanations: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()


class ProjectionGap(DomainModel):
    gap_type: str = "OTHER"
    reason: NonEmptyText
    severity: NonEmptyText
    status: NonEmptyText
    target_claim_ref: str | None = None
    target_question_ref: str | None = None
    suggested_actions: tuple[NonEmptyText, ...] = ()


class ProjectionTimelineEvent(DomainModel):
    event_time: str | None
    time_precision: TimePrecision
    description: NonEmptyText
    validation_status: ValidationStatus
    claim_refs: tuple[NonEmptyText, ...] = ()


class SourceStatisticsView(DomainModel):
    total_sources: int = Field(ge=0)
    evidence_count: int = Field(default=0, ge=0)
    independent_families: int = Field(ge=0)


class WriterProjection(DomainModel):
    """Bounded writer input: no URLs, locators, quote hashes, or blob refs."""

    report_type: ReportType
    completion_level: str | None = None
    stop_reason: str | None = None
    unassessed_claims: int = 0
    schema_version: NonEmptyText
    investigation_title: NonEmptyText
    terminal_run_status: str = "UNKNOWN"
    investigation_goal: NonEmptyText
    questions: tuple[NonEmptyText, ...]
    claims: tuple[ProjectionClaim, ...]
    conflicts: tuple[ProjectionConflict, ...]
    gaps: tuple[ProjectionGap, ...]
    timeline: tuple[ProjectionTimelineEvent, ...]
    limitations: tuple[NonEmptyText, ...]
    source_statistics: SourceStatisticsView
    execution_provenance: str = "PROVIDER_WORKFLOW"

    @classmethod
    def build(
        cls,
        snapshot: ReportInputSnapshot,
        report_type: ReportType,
        *,
        investigation_title: str,
        investigation_goal: str,
    ) -> WriterProjection:
        payload = snapshot.semantic_payload
        families = {source.family_key for source in payload.sources}
        return cls(
            report_type=report_type,
            execution_provenance=payload.execution_provenance,
            schema_version=payload.schema_version,
            investigation_title=investigation_title,
            terminal_run_status=payload.terminal_run_status,
            investigation_goal=investigation_goal,
            questions=payload.questions,
            claims=tuple(
                ProjectionClaim(
                    stable_key=claim.stable_key,
                    statement=claim.statement,
                    claim_type=claim.claim_type,
                    validation_status=claim.validation_status,
                    confidence=claim.confidence,
                    importance=claim.importance,
                    is_critical=claim.is_critical,
                    report_section=claim.report_section,
                    supporting_relations=sum(
                        r.claim_stable_key == claim.stable_key and r.stance == "SUPPORTS"
                        for r in payload.relations
                    ),
                    contradicting_relations=sum(
                        r.claim_stable_key == claim.stable_key and r.stance == "CONTRADICTS"
                        for r in payload.relations
                    ),
                )
                for claim in payload.claims
            ),
            conflicts=tuple(
                ProjectionConflict(
                    stable_key=conflict.stable_key,
                    conflict_type=str(conflict.conflict_type),
                    severity=conflict.severity,
                    status=conflict.status,
                    claim_refs=conflict.claim_stable_keys,
                    resolution_summary=conflict.resolution_summary,
                    possible_explanations=conflict.possible_explanations,
                    observations=tuple(
                        json.dumps(value, ensure_ascii=False, sort_keys=True)
                        for value in conflict.competing_values
                    ),
                )
                for conflict in payload.conflicts
            ),
            gaps=tuple(
                ProjectionGap(
                    gap_type=str(gap.gap_type),
                    reason=gap.reason,
                    severity=str(gap.severity),
                    status=str(gap.status),
                    target_claim_ref=gap.target_claim_stable_key,
                    target_question_ref=gap.target_question_stable_key,
                    suggested_actions=gap.suggested_actions,
                )
                for gap in payload.research_gaps
            ),
            timeline=tuple(
                ProjectionTimelineEvent(
                    event_time=event.event_time.isoformat() if event.event_time else None,
                    time_precision=event.time_precision,
                    description=event.description,
                    validation_status=event.validation_status,
                    claim_refs=tuple(
                        claim.stable_key
                        for claim in payload.claims
                        if claim.statement == event.description
                        and claim.validation_status is ValidationStatus.VERIFIED
                    ),
                )
                for event in payload.timeline_events
            ),
            limitations=payload.limitations,
            source_statistics=SourceStatisticsView(
                total_sources=len(payload.sources),
                evidence_count=len(payload.evidence),
                independent_families=len(families - {"UNGROUPED"}),
            ),
        )


class Writer(Protocol):
    async def draft(self, projection: WriterProjection) -> ReportDraft: ...


class DeterministicWriter:
    """Rule-based Writer for offline/replay-deterministic drafting.

    Applies only status-preserving templating: it paraphrases nothing away,
    keeps every qualifier implied by validation status, and never invents
    facts beyond claim statements.
    """

    async def draft(self, projection: WriterProjection) -> ReportDraft:
        from marketpulse.investigation.reporting.chinese_writer import chinese_draft

        return chinese_draft(projection)
