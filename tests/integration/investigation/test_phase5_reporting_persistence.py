from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import Claim
from marketpulse.investigation.domain.enums import (
    ArtifactType,
    ClaimImportance,
    ClaimType,
    FindingSeverity,
    ParseStatus,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ReportValidatorKind,
    ReviewDecisionOrigin,
    ReviewDecisionType,
    RunMode,
    RunStatus,
    SourceType,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.locators import TextRangeLocator
from marketpulse.investigation.domain.reports import (
    Report,
    ReportProjection,
    ReviewDecision,
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
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.models import (
    Citation,
    CitationSemanticIdentity,
    ReleasePolicyEvaluation,
    ReportInputSemanticPayload,
    ReportInputSnapshot,
    ReportValidationFinding,
    SnapshotClaim,
    SnapshotEvidence,
)
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.review.models import (
    RecordedHumanReviewDecision,
    ReviewerAuthState,
    ReviewerSession,
    ReviewIdempotencyRecord,
    ReviewRateBucket,
    ReviewRequest,
    ReviewResearchRequest,
)

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
CONTENT = b"Phase 5 persistence fixture text"
CONTENT_HASH = hashlib.sha256(CONTENT).hexdigest()
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _payload(statement: str = "The event occurred.") -> ReportInputSemanticPayload:
    return ReportInputSemanticPayload(
        schema_version="phase5-report-input-v1",
        validation_policy_version="phase4-validation-v1",
        investigation_key="investigation:public-event",
        terminal_run_status="READY_FOR_REPORT",
        questions=("What happened?",),
        claims=(
            SnapshotClaim(
                stable_key="claim:event-occurred",
                semantic_hash=HASH_A,
                statement=statement,
                claim_type="EVENT_FACT",
                validation_status="VERIFIED",
                confidence=0.97,
                validation_semantic_hash=HASH_B,
                importance="HIGH",
                is_critical=True,
            ),
        ),
        evidence=(
            SnapshotEvidence(
                stable_key="evidence:official-record",
                semantic_hash=HASH_B,
                content_hash=CONTENT_HASH,
                artifact_content_hash=HASH_A,
                snapshot_content_hash=HASH_B,
                source_semantic_key="source:agency:record",
            ),
        ),
    )


def _seed_base(repository: InvestigationRepository) -> None:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Phase 5 persistence",
            event_description="A public event.",
            investigation_goal="Verify report governance persistence.",
            scope=InvestigationScope(summary="Public records"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="RUN-001",
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
        Source(
            source_id="S-001",
            investigation_id="I-001",
            canonical_url="https://example.test/phase5",
            title="Official record",
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
            content_size=len(CONTENT),
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
            content=CONTENT.decode(),
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
            statement="The event occurred.",
            claim_type=ClaimType.EVENT_FACT,
            importance=ClaimImportance.HIGH,
            is_critical=True,
            validation_status=ValidationStatus.VERIFIED,
            confidence=0.97,
            created_at=NOW,
            updated_at=NOW,
        )
    )


def _snapshot() -> ReportInputSnapshot:
    return ReportInputSnapshot.build(
        snapshot_id="SNAP-001",
        investigation_id="I-001",
        run_id="RUN-001",
        run_mode=RunMode.LIVE,
        assembled_at=NOW,
        semantic_payload=_payload(),
    )


def _report(snapshot: ReportInputSnapshot) -> Report:
    return Report(
        report_id="R-001",
        investigation_id="I-001",
        run_id="RUN-001",
        version=1,
        report_type=ReportType.FULL_INVESTIGATION,
        report_input_snapshot_hash=snapshot.snapshot_hash,
        report_hash=HASH_C,
        claim_set_hash=snapshot.claim_set_hash,
        citation_set_hash=HASH_D,
        release_policy_version="release-v1",
        created_at=NOW,
    )


def _citation(snapshot: ReportInputSnapshot, report: Report) -> Citation:
    identity = CitationSemanticIdentity(
        report_input_snapshot_hash=snapshot.snapshot_hash,
        claim_set_hash=snapshot.claim_set_hash,
        section_key="VERIFIED_FINDINGS",
        unit_key="finding-1",
        claim_semantic_hash=HASH_A,
        validation_semantic_hash=HASH_B,
        relation_semantics="SUPPORTS:ENTAILED",
        evidence_semantic_hash=HASH_B,
        canonical_locator={"kind": "TEXT_RANGE", "start": 0, "end": 19},
        resolved_quote_hash=CONTENT_HASH,
        artifact_content_hash=HASH_A,
        snapshot_content_hash=HASH_B,
        source_semantic_identity="source:agency:record",
        entailment_judgment="ENTAILED",
        entailment_version="semantic-entailment-v1",
        schema_version="citation-v1",
    )
    return Citation.issue(
        citation_id="CIT-001",
        report_id=report.report_id,
        display_ordinal=0,
        claim_id="C-001",
        evidence_id="E-001",
        created_at=NOW,
        identity=identity,
    )


def _evaluation(report: Report) -> ReleasePolicyEvaluation:
    return ReleasePolicyEvaluation.build(
        evaluation_id="EVA-001",
        report_id=report.report_id,
        policy_version="release-v1",
        decision=ReleaseDecision.REQUIRE_REVIEW,
        release_status=ReportReleaseStatus.REVIEW_REQUIRED,
        review_status=ReportReviewStatus.PENDING,
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        citation_set_hash=report.citation_set_hash,
        hard_finding_count=0,
        governance_finding_count=1,
        basis={"governance_codes": ["OFFICIAL_CAPACITY_LIMIT"]},
        created_at=NOW,
    )


def _seed_report_graph(
    repository: InvestigationRepository,
) -> tuple[ReportInputSnapshot, Report, ReleasePolicyEvaluation]:
    _seed_base(repository)
    snapshot = _snapshot()
    report = _report(snapshot)
    evaluation = _evaluation(report)
    repository.add(snapshot)
    repository.add(report)
    repository.add(_citation(snapshot, report))
    repository.add(
        ReportValidationFinding(
            finding_id="FND-001",
            report_id=report.report_id,
            validator=ReportValidatorKind.REPORT,
            severity=FindingSeverity.GOVERNANCE,
            code="OFFICIAL_CAPACITY_LIMIT",
            detail="Governance ceiling requires review.",
            section_key="VERIFIED_FINDINGS",
            validator_version="report-validator-v1",
            created_at=NOW,
        )
    )
    repository.add(evaluation)
    return snapshot, report, evaluation


def test_phase5_governance_entities_round_trip(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    sessions = create_session_factory(engine)
    governance = ReportGovernanceRepository(sessions)
    snapshot, report, evaluation = _seed_report_graph(repository)

    loaded_snapshot = repository.get(ReportInputSnapshot, snapshot.snapshot_id)
    assert loaded_snapshot.snapshot_hash == snapshot.snapshot_hash
    assert loaded_snapshot.semantic_payload.claims[0].statement == "The event occurred."
    with sessions() as session:
        by_hash = governance.snapshot_by_hash_in_session(session, snapshot.snapshot_hash)
        assert by_hash is not None and by_hash.snapshot_id == snapshot.snapshot_id
        assert (
            governance.latest_snapshot_for_run_in_session(session, "RUN-001").snapshot_id
            == snapshot.snapshot_id
        )

    loaded_report = repository.get(Report, report.report_id)
    assert loaded_report.citation_set_hash == HASH_D
    assert loaded_report.schema_version == "phase5-report-v1"

    with sessions() as session:
        citations = governance.citations_for_report_in_session(session, report.report_id)
        assert [citation.citation_id for citation in citations] == ["CIT-001"]
        assert citations[0].citation_hash == citations[0].semantic_identity().semantic_hash
        findings = governance.findings_for_report_in_session(session, report.report_id)
        assert findings[0].severity is FindingSeverity.GOVERNANCE
        latest = governance.latest_evaluation_in_session(session, report.report_id)
        assert latest is not None and latest.evaluation_hash == evaluation.evaluation_hash

    request = ReviewRequest(
        request_id="RRQ-001",
        report_id=report.report_id,
        report_version=1,
        snapshot_hash=snapshot.snapshot_hash,
        claim_set_hash=report.claim_set_hash,
        citation_set_hash=report.citation_set_hash,
        report_hash=report.report_hash,
        evaluation_hash=evaluation.evaluation_hash,
        evaluation_id=evaluation.evaluation_id,
        validator_version="report-validator-v1",
        policy_version="release-v1",
        trigger_reason="Governance finding requires review.",
        created_at=NOW,
        expires_at=LATER + timedelta(days=7),
    )
    repository.add(request)
    with sessions() as session:
        pending = governance.pending_request_for_report_in_session(session, report.report_id, NOW)
        assert pending is not None and pending.request_id == "RRQ-001"

    decision = ReviewDecision(
        review_id="REV-001",
        report_id=report.report_id,
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        reason="All governance bindings verified.",
        report_version=1,
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        release_policy_version="release-v1",
        review_request_id="RRQ-001",
        reviewer_session_public_id="SES-001",
        reviewer_config_fingerprint=HASH_A,
        decision_origin=ReviewDecisionOrigin.LIVE,
        created_at=NOW,
    )
    repository.add(decision)
    loaded_decision = repository.get(ReviewDecision, "REV-001")
    assert loaded_decision.decision_origin is ReviewDecisionOrigin.LIVE
    assert loaded_decision.reviewer_session_public_id == "SES-001"
    with sessions() as session:
        assert (
            governance.pending_request_for_report_in_session(session, report.report_id, NOW) is None
        )

    repository.add(
        ReviewResearchRequest(
            request_id="RRR-001",
            review_id="REV-001",
            report_id=report.report_id,
            reason="Need one more primary source.",
            created_at=NOW,
        )
    )
    assert repository.get(ReviewResearchRequest, "RRR-001").follow_up_run_id is None

    recorded = RecordedHumanReviewDecision.build(
        recorded_id="REC-001",
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        reason="All governance bindings verified.",
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        snapshot_hash=snapshot.snapshot_hash,
        citation_set_hash=report.citation_set_hash,
        release_policy_version="release-v1",
        evaluation_hash=evaluation.evaluation_hash,
        created_at=NOW,
    )
    repository.add(recorded)
    with sessions() as session:
        replayed = governance.recorded_decision_by_fingerprint_in_session(
            session, recorded.semantic_fingerprint
        )
        assert replayed is not None and replayed.recorded_id == "REC-001"

    idempotency = ReviewIdempotencyRecord(
        idempotency_key="approve:R-001:1",
        report_id=report.report_id,
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        response_payload={"review_id": "REV-001"},
        created_at=NOW,
    )
    repository.add(idempotency)
    with sessions() as session:
        assert (
            governance.get_idempotency_in_session(session, "approve:R-001:1").response_payload[
                "review_id"
            ]
            == "REV-001"
        )

    reviewer_session = ReviewerSession(
        session_public_id="SES-001",
        reviewer_id="reviewer-1",
        token_hash=HASH_B,
        reviewer_config_fingerprint=HASH_A,
        generation=1,
        created_at=NOW,
        expires_at=LATER,
    )
    with sessions.begin() as session:
        governance.save_session_in_session(session, reviewer_session)
        governance.save_auth_state_in_session(
            session,
            ReviewerAuthState(
                reviewer_id="reviewer-1",
                active_session_public_id="SES-001",
                active_generation=1,
                config_fingerprint=HASH_A,
                updated_at=NOW,
            ),
        )
        governance.save_rate_bucket_in_session(
            session,
            ReviewRateBucket(
                bucket_fingerprint=HASH_C,
                failure_count=1,
                window_started_at=NOW,
                updated_at=NOW,
            ),
        )
    with sessions.begin() as session:
        found = governance.session_by_token_hash_in_session(session, HASH_B)
        assert found is not None and found.session_public_id == "SES-001"
        governance.save_session_in_session(session, found.model_copy(update={"revoked_at": LATER}))
    with sessions() as session:
        revoked = governance.session_by_token_hash_in_session(session, HASH_B)
        assert revoked is not None and revoked.revoked_at is not None
        state = governance.get_auth_state_in_session(session, "reviewer-1")
        assert state is not None and state.active_generation == 1
        bucket = governance.get_rate_bucket_in_session(session, HASH_C)
        assert bucket is not None and bucket.failure_count == 1

    projection = ReportProjection(
        report_id=report.report_id,
        investigation_id="I-001",
        review_status=ReportReviewStatus.PENDING,
        release_status=ReportReleaseStatus.REVIEW_REQUIRED,
        active_review_request_id="RRQ-001",
        latest_evaluation_id=evaluation.evaluation_id,
        updated_at=NOW,
    )
    with sessions.begin() as session:
        governance.save_projection_in_session(session, projection)
    with sessions.begin() as session:
        current = governance.get_projection_in_session(session, report.report_id)
        assert current is not None
        governance.save_projection_in_session(
            session,
            current.model_copy(
                update={
                    "release_status": ReportReleaseStatus.PUBLISHED,
                    "review_status": ReportReviewStatus.APPROVED,
                    "updated_at": LATER,
                }
            ),
        )
    with sessions() as session:
        updated = governance.get_projection_in_session(session, report.report_id)
        assert updated is not None
        assert updated.release_status is ReportReleaseStatus.PUBLISHED
        assert updated.review_status is ReportReviewStatus.APPROVED


def test_phase5_append_only_guards(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    _seed_report_graph(repository)

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE inv_report_input_snapshots SET claim_set_hash='x' "
                    "WHERE snapshot_id='SNAP-001'"
                )
            )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM inv_reports WHERE report_id='R-001'"))
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE inv_citations SET unit_key='changed' WHERE citation_id='CIT-001'")
            )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE inv_release_policy_evaluations SET decision='PUBLISH' "
                    "WHERE evaluation_id='EVA-001'"
                )
            )


def test_phase5_snapshot_hash_is_unique(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    _seed_base(repository)
    repository.add(_snapshot())
    duplicate = ReportInputSnapshot.build(
        snapshot_id="SNAP-002",
        investigation_id="I-001",
        run_id="RUN-001",
        run_mode=RunMode.REPLAY,
        assembled_at=LATER,
        semantic_payload=_payload(),
    )
    assert duplicate.snapshot_hash == _snapshot().snapshot_hash
    with pytest.raises(IntegrityError):
        repository.add(duplicate)


def test_phase5_citation_requires_existing_claim_and_evidence(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    _seed_base(repository)
    snapshot = _snapshot()
    report = _report(snapshot)
    repository.add(snapshot)
    repository.add(report)
    orphan = _citation(snapshot, report).model_copy(update={"claim_id": "C-missing"})
    with pytest.raises(IntegrityError):
        repository.add(orphan)


def test_phase5_recorded_decision_fingerprint_is_unique(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, _, _ = investigation_store
    _, report, evaluation = _seed_report_graph(repository)
    snapshot = repository.get(ReportInputSnapshot, "SNAP-001")
    recorded = RecordedHumanReviewDecision.build(
        recorded_id="REC-001",
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        reason="ok",
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        snapshot_hash=snapshot.snapshot_hash,
        citation_set_hash=report.citation_set_hash,
        release_policy_version="release-v1",
        evaluation_hash=evaluation.evaluation_hash,
        created_at=NOW,
    )
    repository.add(recorded)
    with pytest.raises(IntegrityError):
        repository.add(recorded.model_copy(update={"recorded_id": "REC-002"}))
