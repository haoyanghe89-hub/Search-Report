from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ResearchGap,
    TimelineEvent,
    ValidationResult,
)
from marketpulse.investigation.domain.enums import (
    ArtifactType,
    ClaimImportance,
    ClaimType,
    EntailmentStatus,
    FindingSeverity,
    GapSeverity,
    GapStatus,
    ParseStatus,
    RelationStance,
    ReportType,
    ResearchGapType,
    RunMode,
    RunStatus,
    SourceType,
    TimePrecision,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.locators import TextRangeLocator
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationQuestion,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.pipeline import ReportPipeline
from marketpulse.investigation.reporting.writer import DeterministicWriter

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
CONTENT = "The agency confirmed the derailment on the record at 9pm."
CONTENT_HASH = hashlib.sha256(CONTENT.encode()).hexdigest()


def _seed(repository: InvestigationRepository) -> None:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Pipeline investigation",
            event_description="A public event.",
            investigation_goal="Establish what happened.",
            scope=InvestigationScope(summary="Public records"),
            questions=(
                InvestigationQuestion(question_id="Q-001", text="What happened?", is_critical=True),
            ),
            critical_question_ids=("Q-001",),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="RUN-001",
            investigation_id="I-001",
            mode=RunMode.LIVE,
            status=RunStatus.READY_FOR_REPORT,
            current_phase=WorkflowPhase.REPORT,
            checkpoint_version=3,
            state_version=3,
            workflow_version="workflow-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        Source(
            source_id="S-001",
            investigation_id="I-001",
            canonical_url="https://example.test/official",
            title="Official record",
            publisher="Example Agency",
            organization="Example Agency",
            source_type=SourceType.OFFICIAL_REPORT,
            is_official=True,
            is_first_hand=True,
            discovered_at=NOW,
        )
    )
    repository.add(
        SourceSnapshot(
            snapshot_id="SS-001",
            source_id="S-001",
            run_id="RUN-001",
            retrieved_at=NOW,
            raw_blob_ref=BlobRef(CONTENT_HASH),
            raw_sha256=CONTENT_HASH,
            cleaned_blob_ref=BlobRef(CONTENT_HASH),
            cleaned_sha256=CONTENT_HASH,
            mime_type="text/plain",
            encoding="utf-8",
            content_size=len(CONTENT),
            http_status=200,
            parse_status=ParseStatus.PARSED,
            parser_name="fixture",
            parser_version="1",
            normalizer_version="1",
            evidence_eligible=True,
        )
    )
    repository.add(
        DocumentArtifact(
            artifact_id="A-001",
            snapshot_id="SS-001",
            artifact_type=ArtifactType.PLAIN_TEXT,
            blob_ref=BlobRef(CONTENT_HASH),
            sha256=CONTENT_HASH,
            processor_name="fixture",
            processor_version="1",
            created_at=NOW,
        )
    )
    repository.add(
        Evidence(
            evidence_id="E-001",
            run_id="RUN-001",
            snapshot_id="SS-001",
            artifact_id="A-001",
            content=CONTENT,
            content_hash=CONTENT_HASH,
            locator=TextRangeLocator(start=0, end=len(CONTENT), quote_hash=CONTENT_HASH),
            extracted_at=NOW,
            extractor_name="fixture",
            extractor_version="1",
        )
    )
    repository.add(
        Claim(
            claim_id="C-001",
            investigation_id="I-001",
            run_id="RUN-001",
            statement="The agency confirmed the event.",
            claim_type=ClaimType.INSTITUTIONAL_ACTION,
            importance=ClaimImportance.CRITICAL,
            is_critical=True,
            validation_status=ValidationStatus.VERIFIED,
            confidence=0.97,
            latest_validation_id="V-001",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        ClaimEvidenceRelation(
            relation_id="CE-001",
            claim_id="C-001",
            evidence_id="E-001",
            stance=RelationStance.SUPPORTS,
            entailment_status=EntailmentStatus.ENTAILED,
            entailment_score=0.99,
            created_at=NOW,
        )
    )
    repository.add(
        ValidationResult(
            validation_id="V-001",
            claim_id="C-001",
            run_id="RUN-001",
            claim_type=ClaimType.INSTITUTIONAL_ACTION,
            profile_version="profile-v1",
            policy_version="phase4-validation-v1",
            citation_valid=True,
            entailment_result=EntailmentStatus.ENTAILED,
            independent_source_count=1,
            strong_contradiction=False,
            sufficiency_result="sufficient",
            status=ValidationStatus.VERIFIED,
            confidence=0.97,
            validation_basis="Direct institutional record.",
            created_at=NOW,
        )
    )
    repository.add(
        ResearchGap(
            gap_id="G-001",
            investigation_id="I-001",
            run_id="RUN-001",
            gap_type=ResearchGapType.INSUFFICIENT_INDEPENDENCE,
            target_claim_id="C-001",
            reason="Only one independent family available.",
            severity=GapSeverity.MEDIUM,
            status=GapStatus.OPEN,
            created_at=NOW,
        )
    )
    repository.add(
        TimelineEvent(
            timeline_event_id="T-001",
            investigation_id="I-001",
            run_id="RUN-001",
            event_time=NOW,
            time_precision=TimePrecision.EXACT,
            description="The agency published the record.",
            supporting_evidence_ids=("E-001",),
            validation_status=ValidationStatus.VERIFIED,
        )
    )


def _pipeline(engine: Engine) -> ReportPipeline:
    sessions = create_session_factory(engine)
    return ReportPipeline(sessions, InvestigationRepository(sessions), DeterministicWriter())


async def test_pipeline_generates_cited_report(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed(repository)

    result = await _pipeline(engine).generate(
        run_id="RUN-001", report_type=ReportType.FULL_INVESTIGATION, now=NOW
    )

    assert result.hard_finding_count == 0
    assert result.report.version == 1
    assert result.report.report_input_snapshot_hash == result.snapshot.snapshot_hash
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.claim_id == "C-001"
    assert citation.evidence_id == "E-001"
    assert citation.resolved_quote_hash == CONTENT_HASH
    assert "[1]" in result.markdown

    with engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM inv_reports WHERE report_id=:r"),
                {"r": result.report.report_id},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM inv_report_sections WHERE report_id=:r"),
                {"r": result.report.report_id},
            )
            == 15
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM inv_citations WHERE report_id=:r"),
                {"r": result.report.report_id},
            )
            == 1
        )
        assert (
            connection.scalar(
                text("SELECT release_status FROM inv_report_projections WHERE report_id=:r"),
                {"r": result.report.report_id},
            )
            == "PUBLISHED"
        )

    # Second run over unchanged state: new report version, identical semantic hashes.
    result2 = await _pipeline(engine).generate(
        run_id="RUN-001", report_type=ReportType.FULL_INVESTIGATION, now=NOW + timedelta(hours=1)
    )
    assert result2.report.version == 2
    assert result2.report.report_hash == result.report.report_hash
    assert result2.report.claim_set_hash == result.report.claim_set_hash
    assert result2.report.citation_set_hash == result.report.citation_set_hash
    assert result2.snapshot.snapshot_hash == result.snapshot.snapshot_hash


async def test_pipeline_fails_closed_on_claim_drift(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed(repository)
    pipeline = _pipeline(engine)
    await pipeline.generate(run_id="RUN-001", report_type=ReportType.FULL_INVESTIGATION, now=NOW)

    # Tamper with the claim statement after the snapshot exists: re-validating the
    # persisted citation against current state must fail closed.
    result = await pipeline.generate(
        run_id="RUN-001", report_type=ReportType.FULL_INVESTIGATION, now=NOW
    )
    assert result.hard_finding_count == 0
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE inv_claims SET statement='The agency denied everything.' "
                "WHERE claim_id='C-001'"
            )
        )

    from marketpulse.investigation.reporting.citations import CitationFactory

    sessions = create_session_factory(engine)
    factory = CitationFactory(InvestigationRepository(sessions))
    with sessions() as session:
        _, findings = factory.build(
            session,
            snapshot=result.snapshot,
            draft=result.draft,
            report=result.report,
            now=NOW + timedelta(hours=2),
        )
    hard_codes = {finding.code for finding in findings if finding.severity is FindingSeverity.HARD}
    assert "CITATION_CLAIM_DRIFT" in hard_codes
