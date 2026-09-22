"""Phase 5 report pipeline orchestration.

Chain: persisted Phase 4.3 state -> ReportInputAssembler -> immutable snapshot
-> bounded WriterProjection -> structured Writer draft -> CitationFactory ->
CitationValidator -> ReportValidator -> (release policy injected upstream) ->
atomic persistence of report version, sections, citations, and findings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.base import DomainModel, NonEmptyText
from marketpulse.investigation.domain.enums import (
    ConflictStatus,
    ReportReviewStatus,
    ReportType,
    ValidationStatus,
)
from marketpulse.investigation.domain.reports import Report, ReportProjection, ReportSection
from marketpulse.investigation.domain.runtime import Investigation, InvestigationRun
from marketpulse.investigation.persistence.models import ReportRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.assembler import ReportInputAssembler
from marketpulse.investigation.reporting.citations import CitationFactory
from marketpulse.investigation.reporting.models import (
    Citation,
    ReportInputSnapshot,
    ReportValidationFinding,
)
from marketpulse.investigation.reporting.release import (
    RELEASE_POLICY_VERSION,
    ReleasePolicyInput,
    ReportReleasePolicy,
)
from marketpulse.investigation.reporting.renderer import (
    compute_citation_set_hash,
    compute_report_hash,
    render_markdown,
)
from marketpulse.investigation.reporting.validation import CitationValidator, ReportValidator
from marketpulse.investigation.reporting.writer import (
    ReportDraft,
    Writer,
    WriterProjection,
)


class PipelineResult(DomainModel):
    report: Report
    snapshot: ReportInputSnapshot
    draft: ReportDraft
    citations: tuple[Citation, ...]
    findings: tuple[ReportValidationFinding, ...]
    markdown: NonEmptyText

    @property
    def hard_finding_count(self) -> int:
        return sum(1 for finding in self.findings if str(finding.severity) == "HARD")


class ReportPipeline:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        writer: Writer,
    ) -> None:
        self._sessions = sessions
        self._repository = repository
        self._writer = writer
        self._assembler = ReportInputAssembler(sessions, repository)
        self._citations = CitationFactory(repository)
        self._citation_validator = CitationValidator(repository)
        self._report_validator = ReportValidator()

    async def generate(
        self,
        *,
        run_id: str,
        report_type: ReportType,
        now: datetime,
    ) -> PipelineResult:
        snapshot = self._assembler.assemble(
            run_id=run_id,
            snapshot_id=f"SNAP-{uuid.uuid4().hex[:12]}",
            assembled_at=now,
        )
        with self._sessions() as session:
            run = self._repository.get_in_session(session, InvestigationRun, run_id)
            investigation = self._repository.get_in_session(
                session, Investigation, run.investigation_id
            )
        projection = WriterProjection.build(
            snapshot,
            report_type,
            investigation_title=investigation.title,
            investigation_goal=investigation.investigation_goal,
        )
        draft = await self._writer.draft(projection)
        return self._finalize(
            snapshot=snapshot,
            draft=draft,
            investigation_id=investigation.investigation_id,
            run_id=run_id,
            now=now,
        )

    def _finalize(
        self,
        *,
        snapshot: ReportInputSnapshot,
        draft: ReportDraft,
        investigation_id: str,
        run_id: str,
        now: datetime,
    ) -> PipelineResult:
        report_id = f"RPT-{uuid.uuid4().hex[:12]}"
        report_hash = compute_report_hash(draft)
        with self._sessions() as session:
            version = (
                session.scalar(
                    select(func.count())
                    .select_from(ReportRow)
                    .where(ReportRow.investigation_id == investigation_id)
                )
                or 0
            ) + 1

        placeholder = Report(
            report_id=report_id,
            investigation_id=investigation_id,
            run_id=run_id,
            version=version,
            report_type=draft.report_type,
            report_input_snapshot_hash=snapshot.snapshot_hash,
            report_hash=report_hash,
            claim_set_hash=snapshot.claim_set_hash,
            citation_set_hash="0" * 64,
            release_policy_version=RELEASE_POLICY_VERSION,
            created_at=now,
        )

        with self._sessions() as session:
            citations, citation_findings = self._citations.build(
                session, snapshot=snapshot, draft=draft, report=placeholder, now=now
            )
        citation_set_hash = compute_citation_set_hash(citations)
        report = placeholder.model_copy(update={"citation_set_hash": citation_set_hash})

        with self._sessions() as session:
            citation_findings += self._citation_validator.validate(
                session, citations=citations, snapshot=snapshot, report=report, now=now
            )
        report_findings = self._report_validator.validate(
            draft=draft, snapshot=snapshot, citations=citations, report=report, now=now
        )
        findings = [*citation_findings, *report_findings]

        key_section_keys = {"EXECUTIVE_SUMMARY", "CONCLUSIONS_AND_NEXT_STEPS"}
        claim_status_by_key = {
            claim.stable_key: claim.validation_status for claim in snapshot.semantic_payload.claims
        }
        probable_or_disputed_in_key_sections = any(
            claim_status_by_key.get(ref) in (ValidationStatus.PROBABLE, ValidationStatus.DISPUTED)
            for section in draft.sections
            if section.section_key in key_section_keys
            for unit in section.units
            for ref in unit.claim_refs
        )
        unresolved_conflicts = tuple(
            conflict.stable_key
            for conflict in snapshot.semantic_payload.conflicts
            if conflict.status is not ConflictStatus.RESOLVED
        )
        evaluation = ReportReleasePolicy().evaluate(
            ReleasePolicyInput(
                report_id=report.report_id,
                report_type=report.report_type,
                report_hash=report.report_hash,
                claim_set_hash=report.claim_set_hash,
                citation_set_hash=report.citation_set_hash,
                findings=tuple(findings),
                claims=snapshot.semantic_payload.claims,
                probable_or_disputed_in_key_sections=probable_or_disputed_in_key_sections,
                unresolved_nonblocking_conflicts=unresolved_conflicts,
            ),
            evaluation_id=f"EVA-{report.report_id}",
            created_at=now,
        )

        sections = self._sections(draft, snapshot, report, now)
        with self._sessions.begin() as session:
            self._repository.add_in_session(session, report)
            for section in sections:
                self._repository.add_in_session(session, section)
            for citation in citations:
                self._repository.add_in_session(session, citation)
            for finding in findings:
                self._repository.add_in_session(session, finding)
            self._repository.add_in_session(session, evaluation)
            self._repository.add_in_session(
                session,
                ReportProjection(
                    report_id=report.report_id,
                    investigation_id=investigation_id,
                    review_status=evaluation.review_status,
                    release_status=evaluation.release_status,
                    latest_evaluation_id=evaluation.evaluation_id,
                    updated_at=now,
                ),
            )

        if evaluation.review_status is ReportReviewStatus.PENDING:
            from marketpulse.investigation.review.service import ReportReviewService

            ReportReviewService(self._sessions).open_review_request(
                report_id=report.report_id,
                validator_version="report-validator-v1",
                trigger_reason=", ".join(
                    str(trigger)
                    for trigger in evaluation.basis.get("governance_triggers", [])  # type: ignore[union-attr]
                )
                or "governance review required",
                now=now,
                expires_at=now + timedelta(days=7),
            )

        return PipelineResult(
            report=report,
            snapshot=snapshot,
            draft=draft,
            citations=tuple(citations),
            findings=tuple(findings),
            markdown=render_markdown(draft, citations),
        )

    def _sections(
        self,
        draft: ReportDraft,
        snapshot: ReportInputSnapshot,
        report: Report,
        now: datetime,
    ) -> list[ReportSection]:
        sections: list[ReportSection] = []
        for order, section in enumerate(draft.sections):
            claim_ids: list[str] = []
            for unit in section.units:
                for claim_key in unit.claim_refs:
                    claim_id = snapshot.runtime_references.claim_ids.get(claim_key)
                    if claim_id is not None and claim_id not in claim_ids:
                        claim_ids.append(claim_id)
            sections.append(
                ReportSection(
                    section_id=f"RS-{report.report_id}-{order:02d}",
                    report_id=report.report_id,
                    section_type=section.section_key,
                    order_index=order,
                    structured_content={
                        "status": str(section.status),
                        "units": [
                            {
                                "unit_key": unit.unit_key,
                                "text": unit.text,
                                "content_class": str(unit.content_class),
                                "claim_refs": list(unit.claim_refs),
                            }
                            for unit in section.units
                        ],
                    },
                    claim_ids=tuple(claim_ids),
                    created_at=now,
                )
            )
        return sections
