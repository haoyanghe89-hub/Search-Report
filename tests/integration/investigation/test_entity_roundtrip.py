from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError, IntegrityError

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
    ExternalCallStatus,
    GapSeverity,
    GapStatus,
    ParseStatus,
    RelationStance,
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
from marketpulse.investigation.persistence.repositories import InvestigationRepository

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
RAW = b"Primary source text"
CLEANED = "Primary source text"
RAW_HASH = hashlib.sha256(RAW).hexdigest()
CLEANED_HASH = hashlib.sha256(CLEANED.encode()).hexdigest()
REQUEST_HASH = hashlib.sha256(b"request").hexdigest()
RESPONSE_HASH = hashlib.sha256(b"response").hexdigest()


def _foundation() -> list[object]:
    investigation = Investigation(
        investigation_id="I-001",
        title="Example investigation",
        event_description="A public event.",
        investigation_goal="Build an evidence-grounded account.",
        scope=InvestigationScope(summary="Public records"),
        questions=(
            InvestigationQuestion(question_id="Q-001", text="What happened?", is_critical=True),
        ),
        critical_question_ids=("Q-001",),
        created_at=NOW,
        updated_at=NOW,
    )
    run = InvestigationRun(
        run_id="RUN-001",
        investigation_id="I-001",
        mode=RunMode.LIVE,
        status=RunStatus.RUNNING,
        current_phase=WorkflowPhase.COLLECT,
        checkpoint_version=1,
        state_version=1,
        workflow_version="workflow-v1",
        created_at=NOW,
        started_at=NOW,
        updated_at=NOW,
    )
    step = ExecutionStep(
        step_id="STEP-001",
        run_id="RUN-001",
        step_type=StepType.RESEARCH,
        agent_role=AgentRole.RESEARCHER,
        status=ExecutionStepStatus.COMPLETED,
        attempt=1,
        input_fingerprint=REQUEST_HASH,
        output_refs=("SS-001",),
        executor_instance_id="executor-1",
        started_at=NOW,
        heartbeat_at=NOW,
        completed_at=NOW,
        retryable=True,
    )
    task = ResearchTask(
        task_id="TASK-001",
        investigation_id="I-001",
        run_id="RUN-001",
        target_question_id="Q-001",
        title="Find primary source",
        objective="Obtain the official source.",
        status=ResearchTaskStatus.COMPLETED,
        priority=1,
        query_hints=("official report",),
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )
    source = Source(
        source_id="S-001",
        investigation_id="I-001",
        canonical_url="https://example.test/report",
        title="Official report",
        publisher="Example Board",
        organization="Example Board",
        source_type=SourceType.OFFICIAL_REPORT,
        is_official=True,
        is_first_hand=True,
        discovered_at=NOW,
    )
    snapshot_one = SourceSnapshot(
        snapshot_id="SS-001",
        source_id="S-001",
        run_id="RUN-001",
        retrieved_at=NOW,
        raw_blob_ref=BlobRef(RAW_HASH),
        raw_sha256=RAW_HASH,
        cleaned_blob_ref=BlobRef(CLEANED_HASH),
        cleaned_sha256=CLEANED_HASH,
        mime_type="text/plain",
        encoding="utf-8",
        content_size=len(RAW),
        http_status=200,
        parse_status=ParseStatus.PARSED,
        parser_name="plain",
        parser_version="1",
        normalizer_version="1",
        evidence_eligible=True,
        provenance={"mode": "live"},
    )
    snapshot_two = snapshot_one.model_copy(
        update={"snapshot_id": "SS-002", "retrieved_at": NOW + timedelta(minutes=1)}
    )
    artifact = DocumentArtifact(
        artifact_id="A-001",
        snapshot_id="SS-001",
        artifact_type=ArtifactType.PLAIN_TEXT,
        blob_ref=BlobRef(CLEANED_HASH),
        sha256=CLEANED_HASH,
        processor_name="plain",
        processor_version="1",
        created_at=NOW,
    )
    evidence_one = Evidence(
        evidence_id="E-001",
        run_id="RUN-001",
        snapshot_id="SS-001",
        artifact_id="A-001",
        content=CLEANED,
        content_hash=CLEANED_HASH,
        locator=TextRangeLocator(start=0, end=len(CLEANED), quote_hash=CLEANED_HASH),
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    second_content = "Independent contrary record"
    second_hash = hashlib.sha256(second_content.encode()).hexdigest()
    evidence_two = Evidence(
        evidence_id="E-002",
        run_id="RUN-001",
        snapshot_id="SS-002",
        content=second_content,
        content_hash=second_hash,
        locator=TextRangeLocator(start=0, end=len(second_content), quote_hash=second_hash),
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    claim = Claim(
        claim_id="C-001",
        investigation_id="I-001",
        run_id="RUN-001",
        statement="The institution published a report.",
        claim_type=ClaimType.INSTITUTIONAL_ACTION,
        importance=ClaimImportance.CRITICAL,
        is_critical=True,
        validation_status=ValidationStatus.VERIFIED,
        confidence=0.96,
        confidence_basis="Direct official record.",
        created_at=NOW,
        updated_at=NOW,
    )
    support = ClaimEvidenceRelation(
        relation_id="CE-001",
        claim_id="C-001",
        evidence_id="E-001",
        stance=RelationStance.SUPPORTS,
        entailment_status=EntailmentStatus.ENTAILED,
        entailment_score=0.98,
        created_at=NOW,
    )
    contradiction = ClaimEvidenceRelation(
        relation_id="CE-002",
        claim_id="C-001",
        evidence_id="E-002",
        stance=RelationStance.CONTRADICTS,
        entailment_status=EntailmentStatus.CONTRADICTED,
        entailment_score=0.9,
        created_at=NOW,
    )
    conflict = ConflictSet(
        conflict_id="CF-001",
        investigation_id="I-001",
        run_id="RUN-001",
        claim_ids=("C-001",),
        conflict_type=ConflictType.OTHER,
        severity=ConflictSeverity.MEDIUM,
        status=ConflictStatus.OPEN,
        possible_causes=("Different publication dates",),
        created_at=NOW,
        updated_at=NOW,
    )
    validation = ValidationResult(
        validation_id="V-001",
        claim_id="C-001",
        run_id="RUN-001",
        claim_type=ClaimType.INSTITUTIONAL_ACTION,
        profile_version="profile-v1",
        citation_valid=True,
        entailment_result=EntailmentStatus.ENTAILED,
        independent_source_count=1,
        strong_contradiction=False,
        source_quality_summary={"official": 1},
        sufficiency_result="sufficient",
        status=ValidationStatus.VERIFIED,
        confidence=0.96,
        validation_basis="Direct institutional record.",
        created_at=NOW,
    )
    gap = ResearchGap(
        gap_id="G-001",
        investigation_id="I-001",
        run_id="RUN-001",
        gap_type=ResearchGapType.SOURCE_CONFLICT,
        target_question_id="Q-001",
        target_claim_id="C-001",
        source_id="S-001",
        reason="A contrary record requires resolution.",
        severity=GapSeverity.MEDIUM,
        status=GapStatus.OPEN,
        suggested_actions=("Find another primary record",),
        created_at=NOW,
    )
    timeline = TimelineEvent(
        timeline_event_id="T-001",
        investigation_id="I-001",
        run_id="RUN-001",
        event_time=NOW,
        time_precision=TimePrecision.EXACT,
        description="The report was published.",
        related_entity_ids=("S-001",),
        supporting_evidence_ids=("E-001",),
        validation_status=ValidationStatus.VERIFIED,
    )
    report = Report(
        report_id="R-001",
        investigation_id="I-001",
        run_id="RUN-001",
        version=1,
        report_type=ReportType.RESTRICTED_INVESTIGATION,
        report_input_snapshot_hash=REQUEST_HASH,
        report_hash=RESPONSE_HASH,
        claim_set_hash=CLEANED_HASH,
        citation_set_hash=RAW_HASH,
        release_policy_version="release-v1",
        created_at=NOW,
    )
    section = ReportSection(
        section_id="RS-001",
        report_id="R-001",
        section_type="verified_facts",
        order_index=1,
        structured_content={"text": "The institution published a report."},
        claim_ids=("C-001",),
        created_at=NOW,
    )
    review = ReviewDecision(
        review_id="REV-001",
        report_id="R-001",
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        reason="All hard gates pass.",
        report_version=1,
        report_hash=RESPONSE_HASH,
        claim_set_hash=CLEANED_HASH,
        release_policy_version="release-v1",
        created_at=NOW,
    )
    audit = AuditEvent(
        audit_event_id="AUD-001",
        investigation_id="I-001",
        run_id="RUN-001",
        actor_type=AuditActorType.HUMAN,
        actor_id="reviewer-1",
        event_type="REPORT_APPROVED",
        target_type="report",
        target_id="R-001",
        metadata={"review_id": "REV-001"},
        created_at=NOW,
    )
    tool_call = RecordedToolCall(
        call_id="TC-001",
        run_id="RUN-001",
        step_id="STEP-001",
        operation="fetch",
        request_fingerprint=REQUEST_HASH,
        request_blob_ref=BlobRef(REQUEST_HASH),
        request_hash=REQUEST_HASH,
        response_blob_ref=BlobRef(RESPONSE_HASH),
        response_hash=RESPONSE_HASH,
        tool_name="fetch-port",
        provider="fixture",
        schema_version="1",
        config_version="runtime-v1",
        attempt=1,
        status=ExternalCallStatus.SUCCESS,
        replayable=True,
        recorded_at=NOW,
        completed_at=NOW,
    )
    model_call = RecordedModelCall(
        call_id="MC-001",
        run_id="RUN-001",
        step_id="STEP-001",
        operation="extract",
        request_fingerprint=RESPONSE_HASH,
        request_blob_ref=BlobRef(REQUEST_HASH),
        request_hash=REQUEST_HASH,
        response_blob_ref=BlobRef(RESPONSE_HASH),
        response_hash=RESPONSE_HASH,
        provider="fixture",
        model="fixture-model",
        schema_version="1",
        prompt_version="extract-v1",
        config_version="runtime-v1",
        attempt=1,
        status=ExternalCallStatus.SUCCESS,
        replayable=True,
        recorded_at=NOW,
        completed_at=NOW,
    )
    return [
        investigation,
        run,
        step,
        task,
        source,
        snapshot_one,
        snapshot_two,
        artifact,
        evidence_one,
        evidence_two,
        claim,
        support,
        contradiction,
        conflict,
        validation,
        gap,
        timeline,
        report,
        section,
        review,
        audit,
        tool_call,
        model_call,
    ]


def _entity_id(entity: object) -> str:
    field_by_type = {
        Investigation: "investigation_id",
        InvestigationRun: "run_id",
        ExecutionStep: "step_id",
        ResearchTask: "task_id",
        Source: "source_id",
        SourceSnapshot: "snapshot_id",
        DocumentArtifact: "artifact_id",
        Evidence: "evidence_id",
        Claim: "claim_id",
        ClaimEvidenceRelation: "relation_id",
        ConflictSet: "conflict_id",
        ValidationResult: "validation_id",
        ResearchGap: "gap_id",
        TimelineEvent: "timeline_event_id",
        Report: "report_id",
        ReportSection: "section_id",
        ReviewDecision: "review_id",
        AuditEvent: "audit_event_id",
        RecordedToolCall: "call_id",
        RecordedModelCall: "call_id",
    }
    field = field_by_type[type(entity)]
    return str(getattr(entity, field))


def _seed(repository: InvestigationRepository) -> list[object]:
    entities = _foundation()
    for entity in entities:
        repository.add(entity)  # type: ignore[arg-type]
    return entities


def test_every_core_entity_round_trips_and_preserves_relations(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    entities = _seed(repository)

    for entity in entities:
        loaded = repository.get(type(entity), _entity_id(entity))  # type: ignore[arg-type]
        assert type(loaded) is type(entity)

    investigation = repository.get(Investigation, "I-001")
    assert investigation.critical_question_ids == ("Q-001",)
    assert repository.get(SourceSnapshot, "SS-001").raw_blob_ref.uri.startswith("blob://sha256/")
    assert repository.get(SourceSnapshot, "SS-002").source_id == "S-001"
    assert repository.get(ClaimEvidenceRelation, "CE-001").stance is RelationStance.SUPPORTS
    assert repository.get(ClaimEvidenceRelation, "CE-002").stance is RelationStance.CONTRADICTS
    assert repository.get(ConflictSet, "CF-001").claim_ids == ("C-001",)
    assert repository.get(TimelineEvent, "T-001").supporting_evidence_ids == ("E-001",)
    assert repository.get(ReportSection, "RS-001").claim_ids == ("C-001",)


def test_evidence_cannot_reference_nonexistent_snapshot(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    for entity in _foundation()[:2]:
        repository.add(entity)  # type: ignore[arg-type]
    content = "orphan evidence"
    digest = hashlib.sha256(content.encode()).hexdigest()
    evidence = Evidence(
        evidence_id="E-orphan",
        run_id="RUN-001",
        snapshot_id="SS-missing",
        content=content,
        content_hash=digest,
        locator=TextRangeLocator(start=0, end=len(content), quote_hash=digest),
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    with pytest.raises(IntegrityError):
        repository.add(evidence)


def test_duplicate_claim_evidence_pair_is_prevented(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    _seed(repository)
    duplicate = ClaimEvidenceRelation(
        relation_id="CE-duplicate",
        claim_id="C-001",
        evidence_id="E-001",
        stance=RelationStance.CONTEXT,
        entailment_status=EntailmentStatus.UNCERTAIN,
        created_at=NOW,
    )
    with pytest.raises(IntegrityError):
        repository.add(duplicate)


def test_validation_and_audit_history_are_append_only(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed(repository)
    repository.add(
        repository.get(ValidationResult, "V-001").model_copy(
            update={"validation_id": "V-002", "created_at": NOW + timedelta(seconds=1)}
        )
    )
    repository.add(
        repository.get(AuditEvent, "AUD-001").model_copy(
            update={"audit_event_id": "AUD-002", "created_at": NOW + timedelta(seconds=1)}
        )
    )
    assert [item.validation_id for item in repository.list_validation_results("C-001")] == [
        "V-001",
        "V-002",
    ]
    assert [item.audit_event_id for item in repository.list_audit_events("I-001")] == [
        "AUD-001",
        "AUD-002",
    ]

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE inv_validation_results SET validation_basis='overwritten' "
                    "WHERE validation_id='V-001'"
                )
            )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM inv_audit_events WHERE audit_event_id='AUD-001'"))


def test_claim_and_evidence_are_physically_separate_tables(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    _, engine, _ = investigation_store
    with engine.connect() as connection:
        claim_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(inv_claims)"))
        }
        evidence_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(inv_evidence)"))
        }
    assert "validation_status" in claim_columns
    assert "validation_status" not in evidence_columns
    assert "locator_payload" in evidence_columns
    assert "locator_payload" not in claim_columns
