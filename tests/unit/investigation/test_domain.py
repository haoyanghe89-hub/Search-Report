from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
    ResearchGap,
    TimelineEvent,
    ValidationResult,
)
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
from marketpulse.investigation.domain.locators import TextRangeLocator
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.domain.reports import (
    AuditEvent,
    Report,
    ReportSection,
    ReviewDecision,
)
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationQuestion,
    InvestigationRun,
    InvestigationScope,
    ResearchTask,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)

NOW = datetime(2026, 9, 21, tzinfo=UTC)
HASH = hashlib.sha256(b"payload").hexdigest()
REF = BlobRef(HASH)


def test_core_domain_entities_are_distinct_and_typed() -> None:
    scope = InvestigationScope(summary="Public-event facts", inclusions=("timeline",))
    question = InvestigationQuestion(question_id="Q-001", text="What happened?", is_critical=True)
    investigation = Investigation(
        investigation_id="I-001",
        title="Example event",
        event_description="An event requiring evidence-grounded investigation.",
        investigation_goal="Establish a traceable account.",
        scope=scope,
        questions=(question,),
        critical_question_ids=("Q-001",),
        created_at=NOW,
        updated_at=NOW,
    )
    run = InvestigationRun(
        run_id="RUN-001",
        investigation_id=investigation.investigation_id,
        mode=RunMode.LIVE,
        status=RunStatus.CREATED,
        current_phase=WorkflowPhase.CREATED,
        checkpoint_version=0,
        state_version=0,
        workflow_version="investigation-v1",
        created_at=NOW,
        updated_at=NOW,
    )
    step = ExecutionStep(
        step_id="STEP-001",
        run_id=run.run_id,
        step_type=StepType.RESEARCH,
        agent_role=AgentRole.RESEARCHER,
        status=ExecutionStepStatus.PENDING,
        attempt=1,
        input_fingerprint=HASH,
        output_refs=(),
        retryable=True,
    )
    task = ResearchTask(
        task_id="TASK-001",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        title="Find primary record",
        objective="Locate the authoritative report.",
        status=ResearchTaskStatus.PENDING,
        priority=1,
        created_at=NOW,
        updated_at=NOW,
    )
    source = Source(
        source_id="S-001",
        investigation_id=investigation.investigation_id,
        canonical_url="https://example.test/report",
        title="Official report",
        publisher="Example Board",
        organization="Example Board",
        source_type=SourceType.OFFICIAL_REPORT,
        is_official=True,
        is_first_hand=True,
        discovered_at=NOW,
    )
    snapshot = SourceSnapshot(
        snapshot_id="SS-001",
        source_id=source.source_id,
        run_id=run.run_id,
        retrieved_at=NOW,
        raw_blob_ref=REF,
        raw_sha256=HASH,
        cleaned_blob_ref=REF,
        cleaned_sha256=HASH,
        mime_type="text/plain",
        encoding="utf-8",
        content_size=7,
        http_status=200,
        parse_status=ParseStatus.PARSED,
        parser_name="plain-text",
        parser_version="1",
        normalizer_version="1",
        evidence_eligible=True,
        provenance={"retrieval": "live"},
    )
    artifact = DocumentArtifact(
        artifact_id="A-001",
        snapshot_id=snapshot.snapshot_id,
        artifact_type=ArtifactType.PLAIN_TEXT,
        blob_ref=REF,
        sha256=HASH,
        processor_name="normalizer",
        processor_version="1",
        created_at=NOW,
    )
    locator = TextRangeLocator(start=0, end=7, quote_hash=HASH)
    evidence = Evidence(
        evidence_id="E-001",
        run_id=run.run_id,
        snapshot_id=snapshot.snapshot_id,
        artifact_id=artifact.artifact_id,
        content="payload",
        content_hash=HASH,
        locator=locator,
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    claim = Claim(
        claim_id="C-001",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        statement="The board published an official report.",
        claim_type=ClaimType.INSTITUTIONAL_ACTION,
        importance=ClaimImportance.HIGH,
        is_critical=True,
        validation_status=ValidationStatus.PENDING,
        created_at=NOW,
        updated_at=NOW,
    )
    relation = ClaimEvidenceRelation(
        relation_id="CE-001",
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        stance=RelationStance.SUPPORTS,
        entailment_status=EntailmentStatus.PENDING,
        created_at=NOW,
    )
    conflict = ConflictSet(
        conflict_id="CF-001",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        claim_ids=(claim.claim_id,),
        conflict_type=ConflictType.OTHER,
        severity=ConflictSeverity.LOW,
        status=ConflictStatus.OPEN,
        created_at=NOW,
        updated_at=NOW,
    )
    validation = ValidationResult(
        validation_id="V-001",
        claim_id=claim.claim_id,
        run_id=run.run_id,
        claim_type=claim.claim_type,
        profile_version="v1",
        citation_valid=True,
        entailment_result=EntailmentStatus.ENTAILED,
        independent_source_count=1,
        strong_contradiction=False,
        source_quality_summary={"official": 1},
        sufficiency_result="sufficient",
        status=ValidationStatus.VERIFIED,
        confidence=0.91,
        validation_basis="Direct official record with exact locator.",
        created_at=NOW,
    )
    gap = ResearchGap(
        gap_id="G-001",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        gap_type=ResearchGapType.EVIDENCE_GAP,
        target_question_id="Q-001",
        reason="Independent corroboration is not yet available.",
        severity=GapSeverity.MEDIUM,
        status=GapStatus.OPEN,
        suggested_actions=("Search independent archives",),
        created_at=NOW,
    )
    timeline = TimelineEvent(
        timeline_event_id="T-001",
        investigation_id=investigation.investigation_id,
        run_id=run.run_id,
        event_time=NOW,
        time_precision=TimePrecision.EXACT,
        description="The report was published.",
        related_entity_ids=(source.source_id,),
        supporting_evidence_ids=(evidence.evidence_id,),
        validation_status=ValidationStatus.VERIFIED,
    )

    assert step.agent_role is AgentRole.RESEARCHER
    assert task.status is ResearchTaskStatus.PENDING
    assert evidence.snapshot_id == snapshot.snapshot_id
    assert not hasattr(evidence, "validation_status")
    assert claim.validation_status is ValidationStatus.PENDING
    assert relation.stance is RelationStance.SUPPORTS
    assert conflict.claim_ids == (claim.claim_id,)
    assert validation.status is ValidationStatus.VERIFIED
    assert gap.gap_type is ResearchGapType.EVIDENCE_GAP
    assert timeline.supporting_evidence_ids == (evidence.evidence_id,)


def test_report_review_audit_and_recording_contracts() -> None:
    report = Report(
        report_id="R-001",
        investigation_id="I-001",
        run_id="RUN-001",
        version=1,
        report_type=ReportType.RESTRICTED_INVESTIGATION,
        review_status=ReportReviewStatus.PENDING,
        release_status=ReportReleaseStatus.REVIEW_REQUIRED,
        report_hash=HASH,
        claim_set_hash=HASH,
        release_policy_version="release-v1",
        created_at=NOW,
        updated_at=NOW,
    )
    section = ReportSection(
        section_id="RS-001",
        report_id=report.report_id,
        section_type="verified_facts",
        order_index=1,
        structured_content={"heading": "Verified facts"},
        claim_ids=("C-001",),
        created_at=NOW,
    )
    decision = ReviewDecision(
        review_id="REV-001",
        report_id=report.report_id,
        reviewer_id="configured-reviewer",
        decision=ReviewDecisionType.APPROVE,
        reason="Evidence and governance gates are satisfied.",
        report_version=1,
        report_hash=HASH,
        claim_set_hash=HASH,
        release_policy_version="release-v1",
        created_at=NOW,
    )
    audit = AuditEvent(
        audit_event_id="AUD-001",
        investigation_id="I-001",
        run_id="RUN-001",
        actor_type=AuditActorType.HUMAN,
        actor_id="configured-reviewer",
        event_type="REPORT_APPROVED",
        target_type="report",
        target_id=report.report_id,
        metadata={"review_id": decision.review_id},
        created_at=NOW,
    )
    tool_call = RecordedToolCall(
        call_id="TC-001",
        run_id="RUN-001",
        step_id="STEP-001",
        operation="search",
        request_fingerprint=HASH,
        request_blob_ref=REF,
        request_hash=HASH,
        response_blob_ref=REF,
        response_hash=HASH,
        tool_name="search-port",
        provider="fixture",
        schema_version="1",
        recorded_at=NOW,
    )
    model_call = RecordedModelCall(
        call_id="MC-001",
        run_id="RUN-001",
        step_id="STEP-001",
        operation="extract_claims",
        request_fingerprint=HASH,
        request_blob_ref=REF,
        request_hash=HASH,
        response_blob_ref=REF,
        response_hash=HASH,
        provider="fixture",
        model="fixture-model",
        schema_version="1",
        prompt_version="extract-v1",
        recorded_at=NOW,
    )

    assert section.claim_ids == ("C-001",)
    assert decision.report_hash == report.report_hash
    assert audit.actor_type is AuditActorType.HUMAN
    assert tool_call.request_blob_ref == REF
    assert model_call.response_blob_ref == REF


def test_replay_recording_rejects_missing_payload_reference() -> None:
    payload = {
        "call_id": "TC-002",
        "run_id": "RUN-001",
        "step_id": "STEP-001",
        "operation": "fetch",
        "request_fingerprint": HASH,
        "request_hash": HASH,
        "response_blob_ref": REF,
        "response_hash": HASH,
        "tool_name": "fetch-port",
        "provider": "fixture",
        "schema_version": "1",
        "recorded_at": NOW,
    }
    with pytest.raises(ValidationError):
        RecordedToolCall.model_validate(payload)


def test_snapshot_rejects_mismatched_blob_hash() -> None:
    with pytest.raises(ValidationError, match="raw_sha256"):
        SourceSnapshot(
            snapshot_id="SS-bad",
            source_id="S-001",
            run_id="RUN-001",
            retrieved_at=NOW,
            raw_blob_ref=REF,
            raw_sha256="0" * 64,
            mime_type="text/plain",
            content_size=7,
            parse_status=ParseStatus.PARSED,
            parser_name="plain",
            parser_version="1",
            normalizer_version="1",
            evidence_eligible=True,
        )
