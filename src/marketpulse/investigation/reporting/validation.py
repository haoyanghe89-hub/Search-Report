"""Phase 5.2 report validation: independent CitationValidator + ReportValidator.

Neither validator mutates Claim status or replaces ValidationPolicy. Any
integrity failure is a HARD finding and fails closed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.orm import Session

from marketpulse.investigation.domain.enums import (
    ConflictStatus,
    FindingSeverity,
    GapStatus,
    ReportType,
    ReportValidatorKind,
    ValidationStatus,
)
from marketpulse.investigation.domain.reports import Report
from marketpulse.investigation.domain.sources import DocumentArtifact, Evidence, SourceSnapshot
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.models import (
    Citation,
    ReportInputSnapshot,
    ReportValidationFinding,
)
from marketpulse.investigation.reporting.writer import (
    ContentClass,
    ReportDraft,
    SectionStatus,
    required_sections,
)

REPORT_VALIDATOR_VERSION = "report-validator-v1"

_PROBABLE_MARKERS = (
    "suggest",
    "likely",
    "probable",
    "appears",
    "indicates",
    "incomplete",
    "uncertain",
)
_DISPUTED_MARKERS = (
    "disputed",
    "conflict",
    "conflicting",
    "unsettled",
    "contradict",
    "disagree",
)
_UNVERIFIED_MARKERS = (
    "not established",
    "could not establish",
    "could not be established",
    "insufficient",
    "unverified",
    "remains unresolved",
)


class CitationValidator:
    """Independently re-verifies every persisted citation chain."""

    def __init__(self, repository: InvestigationRepository) -> None:
        self._repository = repository

    def validate(
        self,
        session: Session,
        *,
        citations: list[Citation],
        snapshot: ReportInputSnapshot,
        report: Report,
        now: datetime,
    ) -> list[ReportValidationFinding]:
        findings: list[ReportValidationFinding] = []
        for citation in citations:
            failure = self._validate_one(session, citation=citation, snapshot=snapshot)
            if failure is not None:
                code, detail = failure
                findings.append(
                    ReportValidationFinding(
                        finding_id=f"FND-{report.report_id}-CVAL-{len(findings):04d}",
                        report_id=report.report_id,
                        validator=ReportValidatorKind.CITATION,
                        severity=FindingSeverity.HARD,
                        code=code,
                        detail=detail,
                        section_key=citation.section_key,
                        unit_key=citation.unit_key,
                        validator_version=REPORT_VALIDATOR_VERSION,
                        created_at=now,
                    )
                )
        return findings

    def _validate_one(
        self, session: Session, *, citation: Citation, snapshot: ReportInputSnapshot
    ) -> tuple[str, str] | None:
        if citation.report_input_snapshot_hash != snapshot.snapshot_hash:
            return "CITATION_SNAPSHOT_BINDING", "citation not bound to current snapshot"
        if citation.semantic_identity().semantic_hash != citation.citation_hash:
            return "CITATION_HASH_MISMATCH", "citation semantic hash does not recompute"
        try:
            evidence = self._repository.get_in_session(session, Evidence, citation.evidence_id)
        except KeyError:
            return "CITATION_EVIDENCE_MISSING", f"evidence {citation.evidence_id} missing"
        locator = evidence.locator
        if locator.model_dump(mode="json") != citation.canonical_locator:
            return "CITATION_LOCATOR_MISMATCH", "locator drifted from citation"
        quote = evidence.content[locator.start : locator.end]
        if hashlib.sha256(quote.encode("utf-8")).hexdigest() != citation.resolved_quote_hash:
            return "CITATION_QUOTE_MISMATCH", "resolved quote hash mismatch"
        snapshot_row = self._repository.get_in_session(
            session, SourceSnapshot, evidence.snapshot_id
        )
        expected_snapshot_hash = snapshot_row.cleaned_sha256 or snapshot_row.raw_sha256
        if expected_snapshot_hash != citation.snapshot_content_hash:
            return "CITATION_SNAPSHOT_HASH_MISMATCH", "snapshot content hash mismatch"
        if evidence.artifact_id is not None:
            artifact = self._repository.get_in_session(
                session, DocumentArtifact, evidence.artifact_id
            )
            if artifact.sha256 != citation.artifact_content_hash:
                return "CITATION_ARTIFACT_HASH_MISMATCH", "artifact content hash mismatch"
        return None


class ReportValidator:
    """Schema, scope, wording, and coverage checks over draft + snapshot."""

    def validate(
        self,
        *,
        draft: ReportDraft,
        snapshot: ReportInputSnapshot,
        citations: list[Citation],
        report: Report,
        now: datetime,
    ) -> list[ReportValidationFinding]:
        findings: list[ReportValidationFinding] = []
        seq = 0

        def emit(
            code: str,
            detail: str,
            section: str | None = None,
            unit: str | None = None,
            claim: str | None = None,
            severity: FindingSeverity = FindingSeverity.HARD,
        ) -> None:
            nonlocal seq
            findings.append(
                ReportValidationFinding(
                    finding_id=f"FND-{report.report_id}-RPT-{seq:04d}",
                    report_id=report.report_id,
                    validator=ReportValidatorKind.REPORT,
                    severity=severity,
                    code=code,
                    detail=detail,
                    section_key=section,
                    unit_key=unit,
                    claim_stable_key=claim,
                    validator_version=REPORT_VALIDATOR_VERSION,
                    created_at=now,
                )
            )
            seq += 1

        # Section completeness: every required section present exactly once.
        required = required_sections(draft.report_type)
        present = [section.section_key for section in draft.sections]
        for key in required:
            if key not in present:
                emit("SCHEMA_SECTION_MISSING", f"required section {key} missing")
        for key in present:
            if key not in required:
                emit("SCHEMA_SECTION_UNKNOWN", f"section {key} not in schema", section=key)
            if present.count(key) > 1:
                emit("SCHEMA_SECTION_DUPLICATED", f"section {key} duplicated", section=key)

        claim_by_key = {claim.stable_key: claim for claim in snapshot.semantic_payload.claims}
        cited_units = {(citation.section_key, citation.unit_key) for citation in citations}
        covered_claims: set[str] = set()

        for section in draft.sections:
            if section.status is SectionStatus.CONTENT and not section.units:
                emit(
                    "SCHEMA_SECTION_EMPTY",
                    f"section {section.section_key} marked CONTENT without units",
                    section=section.section_key,
                )
            for unit in section.units:
                lowered = unit.text.lower()
                if unit.content_class is ContentClass.FACTUAL_ASSERTION:
                    if not unit.claim_refs:
                        emit(
                            "UNSUPPORTED_REPORT_CONTENT",
                            f"factual unit {unit.unit_key} has no claim refs",
                            section.section_key,
                            unit.unit_key,
                        )
                    if unit.evidence_intents and not unit.claim_refs:
                        emit(
                            "EVIDENCE_BYPASSES_CLAIM",
                            f"unit {unit.unit_key} cites evidence without claims",
                            section.section_key,
                            unit.unit_key,
                        )
                    if (section.section_key, unit.unit_key) not in cited_units:
                        emit(
                            "CITATION_INCOMPLETE",
                            f"factual unit {unit.unit_key} lacks a materialized citation",
                            section.section_key,
                            unit.unit_key,
                        )
                for claim_key in unit.claim_refs:
                    claim = claim_by_key.get(claim_key)
                    if claim is None:
                        emit(
                            "UNSUPPORTED_REPORT_CONTENT",
                            f"unit {unit.unit_key} references unknown claim {claim_key}",
                            section.section_key,
                            unit.unit_key,
                            claim_key,
                        )
                        continue
                    covered_claims.add(claim_key)
                    if claim.validation_status is ValidationStatus.PROBABLE and not any(
                        marker in lowered for marker in _PROBABLE_MARKERS
                    ):
                        emit(
                            "QUALIFIER_LOSS",
                            f"PROBABLE claim {claim_key} stated without uncertainty",
                            section.section_key,
                            unit.unit_key,
                            claim_key,
                        )
                    if claim.validation_status is ValidationStatus.DISPUTED and not any(
                        marker in lowered for marker in _DISPUTED_MARKERS
                    ):
                        emit(
                            "STATUS_WORDING_VIOLATION",
                            f"DISPUTED claim {claim_key} stated as settled",
                            section.section_key,
                            unit.unit_key,
                            claim_key,
                        )
                    if claim.validation_status is ValidationStatus.UNVERIFIED and not any(
                        marker in lowered for marker in _UNVERIFIED_MARKERS
                    ):
                        emit(
                            "STATUS_WORDING_VIOLATION",
                            f"UNVERIFIED claim {claim_key} presented as established",
                            section.section_key,
                            unit.unit_key,
                            claim_key,
                        )

        # Critical claim coverage.
        for claim in snapshot.semantic_payload.claims:
            if claim.is_critical and claim.stable_key not in covered_claims:
                emit(
                    "CRITICAL_CLAIM_OMITTED",
                    f"critical claim {claim.stable_key} not covered by report",
                    claim=claim.stable_key,
                )

        # Unresolved conflicts must be surfaced.
        for conflict in snapshot.semantic_payload.conflicts:
            if conflict.status is not ConflictStatus.RESOLVED and conflict.claim_stable_keys:
                if not any(key in covered_claims for key in conflict.claim_stable_keys):
                    emit(
                        "CRITICAL_CONFLICT_OMITTED",
                        f"unresolved conflict {conflict.stable_key} not surfaced",
                        claim=conflict.stable_key,
                    )

        # Open gaps must be disclosed in FULL/RESTRICTED reports.
        if (
            any(gap.status is GapStatus.OPEN for gap in snapshot.semantic_payload.research_gaps)
            and draft.report_type is not ReportType.INVESTIGATION_STATUS
        ):
            limitation_section = next(
                (s for s in draft.sections if s.section_key == "LIMITATIONS_AND_RESEARCH_GAPS"),
                None,
            )
            if limitation_section is None or not limitation_section.units:
                emit("OPEN_GAP_NOT_DISCLOSED", "open research gaps not disclosed")

        return findings
