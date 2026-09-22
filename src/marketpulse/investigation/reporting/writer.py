"""Phase 5.2 Writer: bounded projection, typed narrative units, structured drafts.

The Writer never reads repositories and never receives trusted URLs, locators,
quote hashes, blob references, or source metadata. It receives only a bounded
``WriterProjection`` derived from the immutable ``ReportInputSnapshot`` and
emits typed ``NarrativeUnit`` objects. Every factual unit must carry
``claim_refs``; evidence never bypasses claims.
"""

from __future__ import annotations

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


def required_sections(report_type: ReportType) -> tuple[str, ...]:
    if report_type is ReportType.INVESTIGATION_STATUS:
        return STATUS_SECTIONS
    return FULL_SECTIONS


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


class ProjectionConflict(DomainModel):
    stable_key: NonEmptyText
    conflict_type: NonEmptyText
    severity: ConflictSeverity
    status: ConflictStatus
    claim_refs: tuple[NonEmptyText, ...]


class ProjectionGap(DomainModel):
    reason: NonEmptyText
    severity: NonEmptyText
    status: NonEmptyText


class ProjectionTimelineEvent(DomainModel):
    event_time: str | None
    time_precision: TimePrecision
    description: NonEmptyText
    validation_status: ValidationStatus


class SourceStatisticsView(DomainModel):
    total_sources: int = Field(ge=0)
    independent_families: int = Field(ge=0)


class WriterProjection(DomainModel):
    """Bounded writer input: no URLs, locators, quote hashes, or blob refs."""

    report_type: ReportType
    schema_version: NonEmptyText
    investigation_title: NonEmptyText
    investigation_goal: NonEmptyText
    questions: tuple[NonEmptyText, ...]
    claims: tuple[ProjectionClaim, ...]
    conflicts: tuple[ProjectionConflict, ...]
    gaps: tuple[ProjectionGap, ...]
    timeline: tuple[ProjectionTimelineEvent, ...]
    limitations: tuple[NonEmptyText, ...]
    source_statistics: SourceStatisticsView

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
            schema_version=payload.schema_version,
            investigation_title=investigation_title,
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
                )
                for conflict in payload.conflicts
            ),
            gaps=tuple(
                ProjectionGap(
                    reason=gap.reason,
                    severity=str(gap.severity),
                    status=str(gap.status),
                )
                for gap in payload.research_gaps
            ),
            timeline=tuple(
                ProjectionTimelineEvent(
                    event_time=event.event_time.isoformat() if event.event_time else None,
                    time_precision=event.time_precision,
                    description=event.description,
                    validation_status=event.validation_status,
                )
                for event in payload.timeline_events
            ),
            limitations=payload.limitations,
            source_statistics=SourceStatisticsView(
                total_sources=len(payload.sources),
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
        if projection.report_type is ReportType.INVESTIGATION_STATUS:
            return _status_draft(projection)
        return _full_draft(projection)


def _unit(
    section: str, key: str, text: str, content_class: ContentClass, claim_refs: tuple[str, ...] = ()
) -> NarrativeUnit:
    return NarrativeUnit(
        unit_key=f"{section.lower().replace('_', '-')}-{key}",
        section_key=section,
        text=text,
        content_class=content_class,
        claim_refs=claim_refs,
    )


def _claim_sentence(claim: ProjectionClaim) -> str:
    if claim.validation_status is ValidationStatus.VERIFIED:
        return claim.statement
    if claim.validation_status is ValidationStatus.PROBABLE:
        return (
            f"Available evidence suggests, with incomplete certainty, that "
            f"{claim.statement[0].lower() + claim.statement[1:]}"
        )
    if claim.validation_status is ValidationStatus.DISPUTED:
        return f"Remains disputed amid conflicting evidence: {claim.statement}"
    return f"Could not be established on current evidence: {claim.statement}"


def _claims_section(section: str, claims: list[ProjectionClaim]) -> DraftSection:
    if not claims:
        return DraftSection(
            section_key=section, status=SectionStatus.INSUFFICIENT_SUPPORTED_MATERIAL
        )
    units = tuple(
        _unit(
            section,
            claim.stable_key.rsplit(":", 1)[-1],
            _claim_sentence(claim),
            ContentClass.FACTUAL_ASSERTION,
            (claim.stable_key,),
        )
        for claim in claims
    )
    return DraftSection(section_key=section, status=SectionStatus.CONTENT, units=units)


def _full_draft(p: WriterProjection) -> ReportDraft:
    by_status: dict[ValidationStatus, list[ProjectionClaim]] = {}
    for claim in p.claims:
        by_status.setdefault(claim.validation_status, []).append(claim)
    verified = by_status.get(ValidationStatus.VERIFIED, [])
    probable = by_status.get(ValidationStatus.PROBABLE, [])
    disputed = by_status.get(ValidationStatus.DISPUTED, [])
    unverified = by_status.get(ValidationStatus.UNVERIFIED, [])

    sections: list[DraftSection] = []
    sections.append(
        DraftSection(
            section_key="EXECUTIVE_SUMMARY",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "EXECUTIVE_SUMMARY",
                    "overview",
                    f"Investigation '{p.investigation_title}' reached "
                    f"{len(verified)} verified, {len(probable)} probable, "
                    f"{len(disputed)} disputed and {len(unverified)} unestablished claims "
                    f"across {p.source_statistics.total_sources} sources.",
                    ContentClass.ANALYTICAL_SYNTHESIS,
                ),
            ),
        )
    )
    sections.append(
        DraftSection(
            section_key="SCOPE_AND_MANDATE",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "SCOPE_AND_MANDATE", "goal", p.investigation_goal, ContentClass.PRESENTATIONAL
                ),
            ),
        )
    )
    sections.append(
        DraftSection(
            section_key="INVESTIGATION_QUESTIONS",
            status=SectionStatus.CONTENT,
            units=tuple(
                _unit("INVESTIGATION_QUESTIONS", f"q{index}", question, ContentClass.PRESENTATIONAL)
                for index, question in enumerate(p.questions, start=1)
            ),
        )
    )
    sections.append(
        DraftSection(
            section_key="METHODOLOGY",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "METHODOLOGY",
                    "pipeline",
                    "Multi-agent collection, analysis and independent validation; "
                    "every factual statement traces to validated claims and located evidence.",
                    ContentClass.PRESENTATIONAL,
                ),
            ),
        )
    )
    sections.append(
        DraftSection(
            section_key="SOURCE_COVERAGE",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "SOURCE_COVERAGE",
                    "stats",
                    f"The investigation draws on {p.source_statistics.total_sources} sources "
                    f"across {p.source_statistics.independent_families} independent families.",
                    ContentClass.GOVERNANCE_DISCLOSURE,
                ),
            ),
        )
    )
    if p.timeline:
        sections.append(
            DraftSection(
                section_key="TIMELINE",
                status=SectionStatus.CONTENT,
                units=tuple(
                    _unit(
                        "TIMELINE",
                        f"event-{index}",
                        f"[{event.event_time or event.time_precision}] {event.description}",
                        ContentClass.ANALYTICAL_SYNTHESIS,
                    )
                    for index, event in enumerate(p.timeline, start=1)
                ),
            )
        )
    else:
        sections.append(
            DraftSection(
                section_key="TIMELINE", status=SectionStatus.INSUFFICIENT_SUPPORTED_MATERIAL
            )
        )
    sections.append(_claims_section("VERIFIED_FINDINGS", verified))
    sections.append(_claims_section("PROBABLE_FINDINGS", probable))
    sections.append(_claims_section("DISPUTED_FINDINGS", disputed))

    quantitative = [c for c in p.claims if c.claim_type is ClaimType.QUANTITATIVE]
    sections.append(_claims_section("QUANTITATIVE_FINDINGS", quantitative))
    impact = [c for c in p.claims if c.claim_type is ClaimType.IMPACT]
    sections.append(_claims_section("IMPACT_SCOPE_AND_ANALYSIS", impact))
    causal = [c for c in p.claims if c.claim_type is ClaimType.CAUSAL]
    sections.append(_claims_section("CAUSAL_AND_MECHANISM_ANALYSIS", causal))
    attribution = [c for c in p.claims if c.claim_type is ClaimType.ATTRIBUTION]
    sections.append(_claims_section("ACTOR_AND_ATTRIBUTION_ASSESSMENT", attribution))

    if p.conflicts:
        sections.append(
            DraftSection(
                section_key="CONFLICT_ANALYSIS",
                status=SectionStatus.CONTENT,
                units=tuple(
                    _unit(
                        "CONFLICT_ANALYSIS",
                        conflict.stable_key.rsplit(":", 1)[-1],
                        f"A {conflict.conflict_type} conflict ({conflict.severity}) remains "
                        f"{conflict.status}: conflicting accounts span "
                        f"{len(conflict.claim_refs)} claims and are not settled here.",
                        ContentClass.ANALYTICAL_SYNTHESIS,
                        conflict.claim_refs,
                    )
                    for conflict in p.conflicts
                ),
            )
        )
    else:
        sections.append(
            DraftSection(section_key="CONFLICT_ANALYSIS", status=SectionStatus.NOT_APPLICABLE)
        )

    remediation = [c for c in p.claims if c.claim_type is ClaimType.INSTITUTIONAL_ACTION]
    sections.append(_claims_section("REMEDIATION_AND_FOLLOW_UP", remediation))

    limitation_units = tuple(
        _unit(
            "LIMITATIONS_AND_RESEARCH_GAPS",
            f"limitation-{index}",
            limitation,
            ContentClass.GOVERNANCE_DISCLOSURE,
        )
        for index, limitation in enumerate(p.limitations, start=1)
    )
    gap_units = tuple(
        _unit(
            "LIMITATIONS_AND_RESEARCH_GAPS",
            f"gap-{index}",
            f"Open research gap ({gap.severity}): {gap.reason}",
            ContentClass.GOVERNANCE_DISCLOSURE,
        )
        for index, gap in enumerate(p.gaps, start=1)
        if gap.status == "OPEN"
    )
    # UNVERIFIED claims may only be disclosed as not established.
    unverified_units = tuple(
        _unit(
            "LIMITATIONS_AND_RESEARCH_GAPS",
            f"unverified-{claim.stable_key.rsplit(':', 1)[-1]}",
            _claim_sentence(claim),
            ContentClass.GOVERNANCE_DISCLOSURE,
            (claim.stable_key,),
        )
        for claim in unverified
    )
    units = limitation_units + gap_units + unverified_units
    sections.append(
        DraftSection(
            section_key="LIMITATIONS_AND_RESEARCH_GAPS",
            status=SectionStatus.CONTENT if units else SectionStatus.NOT_APPLICABLE,
            units=units,
        )
    )
    sections.append(
        DraftSection(
            section_key="CONCLUSIONS_AND_NEXT_STEPS",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "CONCLUSIONS_AND_NEXT_STEPS",
                    "next",
                    "Conclusions follow strictly from validated claims; open gaps require "
                    "the follow-up research actions listed above.",
                    ContentClass.ANALYTICAL_SYNTHESIS,
                ),
            ),
        )
    )
    return ReportDraft(report_type=p.report_type, sections=tuple(sections))


def _status_draft(p: WriterProjection) -> ReportDraft:
    available = [
        claim
        for claim in p.claims
        if claim.validation_status in (ValidationStatus.VERIFIED, ValidationStatus.PROBABLE)
    ]
    blocking = [gap for gap in p.gaps if gap.status == "OPEN"]
    sections = (
        DraftSection(
            section_key="EXECUTIVE_STATUS",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "EXECUTIVE_STATUS",
                    "status",
                    f"Investigation '{p.investigation_title}' is in progress: "
                    f"{len(p.claims)} claims tracked, {len(blocking)} open blocking gaps.",
                    ContentClass.GOVERNANCE_DISCLOSURE,
                ),
            ),
        ),
        DraftSection(
            section_key="SCOPE_AND_MANDATE",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "SCOPE_AND_MANDATE", "goal", p.investigation_goal, ContentClass.PRESENTATIONAL
                ),
            ),
        ),
        DraftSection(
            section_key="INVESTIGATION_QUESTIONS",
            status=SectionStatus.CONTENT,
            units=tuple(
                _unit("INVESTIGATION_QUESTIONS", f"q{index}", question, ContentClass.PRESENTATIONAL)
                for index, question in enumerate(p.questions, start=1)
            ),
        ),
        DraftSection(
            section_key="SEARCH_AND_SOURCE_SUMMARY",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "SEARCH_AND_SOURCE_SUMMARY",
                    "sources",
                    f"{p.source_statistics.total_sources} sources acquired.",
                    ContentClass.GOVERNANCE_DISCLOSURE,
                ),
            ),
        ),
        _claims_section("AVAILABLE_FINDINGS", available),
        DraftSection(
            section_key="BLOCKING_GAPS_AND_LIMITATIONS",
            status=SectionStatus.CONTENT
            if blocking or p.limitations
            else SectionStatus.NOT_APPLICABLE,
            units=tuple(
                _unit(
                    "BLOCKING_GAPS_AND_LIMITATIONS",
                    f"gap-{index}",
                    gap.reason,
                    ContentClass.GOVERNANCE_DISCLOSURE,
                )
                for index, gap in enumerate(blocking, start=1)
            )
            + tuple(
                _unit(
                    "BLOCKING_GAPS_AND_LIMITATIONS",
                    f"limit-{index}",
                    limitation,
                    ContentClass.GOVERNANCE_DISCLOSURE,
                )
                for index, limitation in enumerate(p.limitations, start=1)
            ),
        ),
        DraftSection(
            section_key="NEXT_STEPS",
            status=SectionStatus.CONTENT,
            units=(
                _unit(
                    "NEXT_STEPS",
                    "next",
                    "Continue evidence collection against open gaps before any full report.",
                    ContentClass.PRESENTATIONAL,
                ),
            ),
        ),
    )
    return ReportDraft(report_type=p.report_type, sections=sections)
