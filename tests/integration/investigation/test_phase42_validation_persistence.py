from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
)
from marketpulse.investigation.domain.enums import (
    ArtifactType,
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    EntailmentStatus,
    ParseStatus,
    RelationStance,
    RunMode,
    RunStatus,
    SemanticJudgmentStatus,
    SourceType,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.ingestion.locators import make_text_locator
from marketpulse.investigation.persistence.models import (
    ClaimRow,
    SemanticJudgmentRow,
    SourceFamilyMemberRow,
    SourceFamilyRow,
    ValidationConflictRow,
    ValidationResultRow,
)
from marketpulse.investigation.validation import (
    EvidenceIntegrityValidator,
    RecognizedArtifactVersions,
    SemanticJudgment,
    ValidationPersistence,
    ValidationPolicy,
    ValidationRequest,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def test_validation_history_families_conflicts_and_latest_projection_are_atomic(
    investigation_store: tuple[object, object, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    from marketpulse.investigation.persistence.base import create_session_factory
    from marketpulse.investigation.persistence.repositories import InvestigationRepository

    assert isinstance(repository, InvestigationRepository)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    sessions = create_session_factory(engine)  # type: ignore[arg-type]
    repository.add(
        Investigation(
            investigation_id="I-VAL",
            title="Validation persistence",
            event_description="Persistence contract",
            investigation_goal="Verify append-only validation",
            scope=InvestigationScope(summary="Phase 4.2"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="RUN-VAL",
            investigation_id="I-VAL",
            mode=RunMode.LIVE,
            status=RunStatus.VERIFYING,
            current_phase=WorkflowPhase.VERIFY,
            checkpoint_version=0,
            state_version=0,
            workflow_version="phase4.2",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    source = Source(
        source_id="S-VAL",
        investigation_id="I-VAL",
        canonical_url="https://example.test/validation",
        title="Official record",
        organization="Agency",
        source_type=SourceType.OFFICIAL_REPORT,
        is_official=True,
        is_first_hand=True,
        author="Agency",
        published_at=NOW,
        discovered_at=NOW,
    )
    repository.add(source)
    quote = "Agency stated X"
    stored = blobs.put_bytes(quote.encode())
    snapshot = SourceSnapshot(
        snapshot_id="SS-VAL",
        source_id=source.source_id,
        run_id="RUN-VAL",
        retrieved_at=NOW,
        raw_blob_ref=stored.ref,
        raw_sha256=stored.ref.sha256,
        cleaned_blob_ref=stored.ref,
        cleaned_sha256=stored.ref.sha256,
        mime_type="text/plain",
        encoding="utf-8",
        content_size=len(quote),
        http_status=200,
        parse_status=ParseStatus.PARSED,
        parser_name="fixture-parser",
        parser_version="1",
        normalizer_version="1",
        evidence_eligible=True,
        provenance={"methodology": "direct record", "data_provenance": "agency"},
    )
    artifact = DocumentArtifact(
        artifact_id="A-VAL",
        snapshot_id=snapshot.snapshot_id,
        artifact_type=ArtifactType.PLAIN_TEXT,
        blob_ref=stored.ref,
        sha256=stored.ref.sha256,
        processor_name="fixture-processor",
        processor_version="1",
        created_at=NOW,
    )
    evidence = Evidence(
        evidence_id="E-VAL",
        run_id="RUN-VAL",
        snapshot_id=snapshot.snapshot_id,
        artifact_id=artifact.artifact_id,
        content=quote,
        content_hash=hashlib.sha256(quote.encode()).hexdigest(),
        locator=make_text_locator(quote, 0, len(quote)),
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    repository.add(snapshot)
    repository.add(artifact)
    repository.add(evidence)
    claim = Claim(
        claim_id="C-VAL",
        investigation_id="I-VAL",
        run_id="RUN-VAL",
        statement="Agency stated X",
        claim_type=ClaimType.STATEMENT,
        importance=ClaimImportance.HIGH,
        created_at=NOW,
        updated_at=NOW,
    )
    relation = ClaimEvidenceRelation(
        relation_id="REL-VAL",
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        stance=RelationStance.SUPPORTS,
        entailment_status=EntailmentStatus.PENDING,
        created_at=NOW,
    )
    repository.add(claim)
    repository.add(relation)
    judgment = SemanticJudgment(
        judgment_id="SJ-VAL",
        run_id="RUN-VAL",
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        judgment=SemanticJudgmentStatus.ENTAILS,
        reason="exact attributed statement",
        semantic_confidence=0.95,
        recorded_judgment_ref="REC-MODEL-1",
        schema_version="1",
        created_at=NOW,
    )
    conflict = ConflictSet(
        conflict_id="CF-VAL",
        investigation_id="I-VAL",
        run_id="RUN-VAL",
        claim_ids=(claim.claim_id,),
        evidence_ids=(evidence.evidence_id,),
        conflict_type=ConflictType.OTHER,
        severity=ConflictSeverity.LOW,
        status=ConflictStatus.RESOLVED,
        resolution_status=ConflictResolutionStatus.RESOLVED_WITH_SCOPE,
        resolution_basis="different scope",
        created_at=NOW,
        updated_at=NOW,
    )
    policy = ValidationPolicy(
        integrity=EvidenceIntegrityValidator(
            blobs=blobs,
            recognized_versions=RecognizedArtifactVersions(
                snapshot_parsers=frozenset({("fixture-parser", "1", "1")}),
                artifact_processors=frozenset({("fixture-processor", "1")}),
            ),
        )
    )
    persistence = ValidationPersistence(sessions, repository)

    def validate(
        validation_id: str,
        created_at: datetime,
        validation_claim: Claim,
    ) -> str:
        request = ValidationRequest(
            validation_id=validation_id,
            created_at=created_at,
            claim=validation_claim,
            relations=(relation,),
            evidence=(evidence,),
            snapshots=(snapshot,),
            artifacts=(artifact,),
            sources=(source,),
            semantic_judgments=(judgment,),
            existing_conflicts=(conflict,),
        )
        outcome = policy.validate(request)
        persisted = persistence.persist(request=request, outcome=outcome)
        assert persisted.status is ValidationStatus.VERIFIED
        return outcome.result.input_fingerprint

    first_fingerprint = validate("V-VAL-1", NOW, claim)
    projected_claim = repository.get(Claim, claim.claim_id)
    second_fingerprint = validate("V-VAL-2", NOW + timedelta(minutes=1), projected_claim)
    assert first_fingerprint == second_fingerprint
    persistence.assert_latest_projection_consistent(claim.claim_id)
    results = repository.list_validation_results(claim.claim_id)
    assert [item.validation_id for item in results] == ["V-VAL-1", "V-VAL-2"]
    assert repository.get(Claim, claim.claim_id).latest_validation_id == "V-VAL-2"

    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SemanticJudgmentRow)) == 1
        assert session.scalar(select(func.count()).select_from(SourceFamilyRow)) == 2
        assert session.scalar(select(func.count()).select_from(SourceFamilyMemberRow)) == 2
        assert session.scalar(select(func.count()).select_from(ValidationConflictRow)) == 2
        assert session.get(ClaimRow, claim.claim_id).latest_validation_id == "V-VAL-2"

    inspector = inspect(engine)  # type: ignore[arg-type]
    assert "ix_inv_validation_input_fingerprint" in {
        item["name"] for item in inspector.get_indexes("inv_validation_results")
    }
    family_fks = inspector.get_foreign_keys("inv_source_family_members")
    assert {item["referred_table"] for item in family_fks} == {
        "inv_source_families",
        "inv_sources",
    }

    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:  # type: ignore[union-attr]
            connection.execute(
                text(
                    "UPDATE inv_validation_results SET policy_version='changed' "
                    "WHERE validation_id='V-VAL-1'"
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:  # type: ignore[union-attr]
            connection.execute(
                SourceFamilyMemberRow.__table__.insert().values(
                    family_record_id="missing-family",
                    source_id=source.source_id,
                )
            )
    with sessions() as session:
        assert session.get(ValidationResultRow, "V-VAL-1").policy_version == "validation-policy-v1"
