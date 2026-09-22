from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

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
    ArtifactType,
    ClaimImportance,
    ClaimType,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    GapSeverity,
    GapStatus,
    ParseStatus,
    RelationStance,
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
from marketpulse.investigation.reporting.assembler import (
    ASSEMBLY_SCHEMA_VERSION,
    AssemblyError,
    ReportInputAssembler,
)
from marketpulse.investigation.reporting.models import ReportInputSnapshot

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
CONTENT = "The agency confirmed the event on the record."
CONTENT_HASH = hashlib.sha256(CONTENT.encode()).hexdigest()


def _seed_phase43_state(
    repository: InvestigationRepository,
    *,
    claim_status: ValidationStatus = ValidationStatus.VERIFIED,
    validation_status: ValidationStatus = ValidationStatus.VERIFIED,
    latest_validation_id: str | None = "V-001",
    run_status: RunStatus = RunStatus.READY_FOR_REPORT,
) -> None:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Phase 5 assembly",
            event_description="A public event.",
            investigation_goal="Verify snapshot assembly.",
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
            status=run_status,
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
            canonical_url="https://example.test/official-record",
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
            validation_status=claim_status,
            confidence=0.97,
            latest_validation_id=latest_validation_id,
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
            status=validation_status,
            confidence=0.97,
            validation_basis="Direct institutional record.",
            created_at=NOW,
        )
    )
    repository.add(
        ConflictSet(
            conflict_id="CF-001",
            investigation_id="I-001",
            run_id="RUN-001",
            claim_ids=("C-001",),
            conflict_type=ConflictType.TEMPORAL,
            severity=ConflictSeverity.LOW,
            status=ConflictStatus.OPEN,
            created_at=NOW,
            updated_at=NOW,
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


def _assembler(engine: Engine) -> ReportInputAssembler:
    sessions = create_session_factory(engine)
    return ReportInputAssembler(sessions, InvestigationRepository(sessions))


def test_assembler_builds_snapshot_from_phase43_state(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository)

    snapshot = _assembler(engine).assemble(
        run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW
    )

    payload = snapshot.semantic_payload
    assert payload.schema_version == ASSEMBLY_SCHEMA_VERSION
    assert payload.validation_policy_version == "phase4-validation-v1"
    assert payload.terminal_run_status == "READY_FOR_REPORT"
    assert payload.questions == ("What happened?",)
    assert [claim.statement for claim in payload.claims] == ["The agency confirmed the event."]
    assert payload.claims[0].validation_status is ValidationStatus.VERIFIED
    assert payload.evidence[0].content_hash == CONTENT_HASH
    assert payload.evidence[0].artifact_content_hash == CONTENT_HASH
    assert payload.relations[0].claim_stable_key == payload.claims[0].stable_key
    assert payload.relations[0].evidence_stable_key == payload.evidence[0].stable_key
    assert payload.conflicts[0].claim_stable_keys == (payload.claims[0].stable_key,)
    assert payload.research_gaps[0].reason == "Only one independent family available."
    assert payload.timeline_events[0].supporting_evidence_stable_keys == (
        payload.evidence[0].stable_key,
    )
    assert payload.sources[0].independence_role == "UNGROUPED"
    assert "Only one independent family available." in payload.limitations
    assert any("TEMPORAL" in item for item in payload.limitations)

    claim_stable_key = payload.claims[0].stable_key
    assert snapshot.runtime_references.claim_ids[claim_stable_key] == "C-001"
    assert snapshot.runtime_references.evidence_ids[payload.evidence[0].stable_key] == "E-001"

    persisted = repository.get(ReportInputSnapshot, "SNAP-001")
    assert persisted.snapshot_hash == snapshot.snapshot_hash


def test_repeated_assembly_is_hash_stable_and_idempotent(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository)
    assembler = _assembler(engine)

    first = assembler.assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)
    second = assembler.assemble(run_id="RUN-001", snapshot_id="SNAP-999", assembled_at=LATER)

    assert first.snapshot_hash == second.snapshot_hash
    assert first.claim_set_hash == second.claim_set_hash
    assert first.source_state_fingerprint == second.source_state_fingerprint
    # Idempotent persistence returns the originally persisted row.
    assert second.snapshot_id == "SNAP-001"
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT count(*) FROM inv_report_input_snapshots"))
    assert count == 1


def test_material_semantic_change_changes_snapshot_hash(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository)
    assembler = _assembler(engine)
    first = assembler.assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE inv_claims SET statement='The agency denied the event.' "
                "WHERE claim_id='C-001'"
            )
        )
    changed = assembler.assemble(run_id="RUN-001", snapshot_id="SNAP-002", assembled_at=LATER)

    assert changed.snapshot_hash != first.snapshot_hash
    assert changed.claim_set_hash != first.claim_set_hash
    assert changed.semantic_payload.claims[0].stable_key != (
        first.semantic_payload.claims[0].stable_key
    )


def test_run_not_ready_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository, run_status=RunStatus.RUNNING)
    with pytest.raises(AssemblyError, match="READY_FOR_REPORT"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)


def test_missing_latest_validation_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository, latest_validation_id=None)
    with pytest.raises(AssemblyError, match="no latest validation"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)


def test_dangling_validation_reference_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository, latest_validation_id="V-missing")
    with pytest.raises(AssemblyError, match="missing ValidationResult"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)


def test_stale_claim_projection_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(
        repository,
        claim_status=ValidationStatus.PROBABLE,
        validation_status=ValidationStatus.VERIFIED,
    )
    with pytest.raises(AssemblyError, match="stale"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)


def test_conflict_referencing_other_run_claim_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository)
    repository.add(
        InvestigationRun(
            run_id="RUN-002",
            investigation_id="I-001",
            mode=RunMode.LIVE,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="workflow-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        Claim(
            claim_id="C-002",
            investigation_id="I-001",
            run_id="RUN-002",
            statement="A claim from another run.",
            claim_type=ClaimType.STATEMENT,
            importance=ClaimImportance.LOW,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        ConflictSet(
            conflict_id="CF-002",
            investigation_id="I-001",
            run_id="RUN-001",
            claim_ids=("C-001", "C-002"),
            conflict_type=ConflictType.ATTRIBUTION,
            severity=ConflictSeverity.MEDIUM,
            status=ConflictStatus.OPEN,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(AssemblyError, match="unknown claims"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)


def test_cross_run_evidence_fails_closed(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_phase43_state(repository)
    repository.add(
        InvestigationRun(
            run_id="RUN-002",
            investigation_id="I-001",
            mode=RunMode.LIVE,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="workflow-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        Evidence(
            evidence_id="E-002",
            run_id="RUN-002",
            snapshot_id="SS-001",
            content=CONTENT,
            content_hash=CONTENT_HASH,
            locator=TextRangeLocator(start=0, end=len(CONTENT), quote_hash=CONTENT_HASH),
            extracted_at=NOW,
            extractor_name="fixture",
            extractor_version="1",
        )
    )
    repository.add(
        ClaimEvidenceRelation(
            relation_id="CE-002",
            claim_id="C-001",
            evidence_id="E-002",
            stance=RelationStance.CONTEXT,
            entailment_status=EntailmentStatus.UNCERTAIN,
            created_at=NOW,
        )
    )
    with pytest.raises(AssemblyError, match="belongs to run"):
        _assembler(engine).assemble(run_id="RUN-001", snapshot_id="SNAP-001", assembled_at=NOW)
