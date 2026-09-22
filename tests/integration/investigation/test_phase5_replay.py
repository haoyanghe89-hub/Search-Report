from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from marketpulse.investigation.domain.enums import (
    ReleaseDecision,
    ReportReleaseStatus,
    ReportType,
    ReviewDecisionType,
    RunMode,
    RunStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.reports import Report
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.models import ReleasePolicyEvaluation
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.review.replay import HumanReviewReplay, ReviewReplayError
from marketpulse.investigation.review.service import ReportReviewService, ReviewerIdentity

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64


def _seed(repository: InvestigationRepository, decision: ReleaseDecision) -> Report:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Replay",
            event_description="A public event.",
            investigation_goal="Verify replay.",
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
            status=RunStatus.READY_FOR_REPORT,
            current_phase=WorkflowPhase.REPORT,
            checkpoint_version=1,
            state_version=1,
            workflow_version="workflow-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    report = Report(
        report_id="R-001",
        investigation_id="I-001",
        run_id="RUN-001",
        version=1,
        report_type=ReportType.FULL_INVESTIGATION,
        report_input_snapshot_hash=HASH_A,
        report_hash=HASH_C,
        claim_set_hash=HASH_B,
        citation_set_hash=HASH_D,
        release_policy_version="release-v1",
        created_at=NOW,
    )
    repository.add(report)
    repository.add(
        ReleasePolicyEvaluation.build(
            evaluation_id="EVA-001",
            report_id=report.report_id,
            policy_version="release-v1",
            decision=decision,
            release_status=(
                ReportReleaseStatus.REVIEW_REQUIRED
                if decision is ReleaseDecision.REQUIRE_REVIEW
                else ReportReleaseStatus.DRAFT
            ),
            review_status=(
                __import__(
                    "marketpulse.investigation.domain.enums", fromlist=["ReportReviewStatus"]
                ).ReportReviewStatus.PENDING
                if decision is ReleaseDecision.REQUIRE_REVIEW
                else __import__(
                    "marketpulse.investigation.domain.enums", fromlist=["ReportReviewStatus"]
                ).ReportReviewStatus.NOT_REQUIRED
            ),
            report_hash=report.report_hash,
            claim_set_hash=report.claim_set_hash,
            citation_set_hash=report.citation_set_hash,
            hard_finding_count=1 if decision is ReleaseDecision.BLOCK else 0,
            governance_finding_count=0,
            basis={
                "approval_target": {"release_status": "PUBLISHED", "review_status": "APPROVED"},
                "rejection_target": {"release_status": "DRAFT", "review_status": "REJECTED"},
            },
            created_at=NOW,
        )
    )
    return report


def test_human_review_replay_with_exact_fingerprint(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed(repository, ReleaseDecision.REQUIRE_REVIEW)
    sessions = create_session_factory(engine)
    service = ReportReviewService(sessions)
    service.open_review_request(
        report_id=report.report_id,
        validator_version="report-validator-v1",
        trigger_reason="governance",
        now=NOW,
        expires_at=LATER,
    )
    outcome = service.record_decision(
        report_id=report.report_id,
        decision=ReviewDecisionType.APPROVE,
        reason="Bindings verified.",
        reviewer=ReviewerIdentity(reviewer_id="reviewer-1", session_public_id="SES-1"),
        now=NOW,
    )
    assert outcome.release_status is ReportReleaseStatus.PUBLISHED

    with sessions() as session:
        from sqlalchemy import select

        from marketpulse.investigation.persistence.models import (
            RecordedHumanReviewDecisionRow,
        )

        recorded_row = session.scalar(select(RecordedHumanReviewDecisionRow))
        assert recorded_row is not None
        fingerprint = recorded_row.semantic_fingerprint

    replay = HumanReviewReplay(sessions).replay(
        report_id=report.report_id, semantic_fingerprint=fingerprint, now=LATER
    )
    # Replay ceiling: never a real PUBLISHED release.
    assert replay.release_status is ReportReleaseStatus.RESTRICTED
    assert replay.would_release_status is ReportReleaseStatus.PUBLISHED

    with sessions() as session:
        from marketpulse.investigation.persistence.models import ReviewDecisionRow

        rows = session.scalars(select(ReviewDecisionRow)).all()
        origins = sorted(row.decision_origin for row in rows)
        assert origins == ["LIVE", "REPLAY"]


def test_replay_rejects_mismatched_fingerprint(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed(repository, ReleaseDecision.REQUIRE_REVIEW)
    sessions = create_session_factory(engine)
    with pytest.raises(ReviewReplayError, match="no recorded decision"):
        HumanReviewReplay(sessions).replay(
            report_id=report.report_id,
            semantic_fingerprint=hashlib.sha256(b"x").hexdigest(),
            now=NOW,
        )


def test_replay_never_reviews_hard_gated_report(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed(repository, ReleaseDecision.BLOCK)
    sessions = create_session_factory(engine)
    # Record a decision bound to the real BLOCK evaluation hash.
    from marketpulse.investigation.review.models import RecordedHumanReviewDecision

    governance = ReportGovernanceRepository(sessions)
    with sessions() as session:
        evaluation = governance.latest_evaluation_in_session(session, report.report_id)
        assert evaluation is not None
    recorded = RecordedHumanReviewDecision.build(
        recorded_id="REC-1",
        reviewer_id="reviewer-1",
        decision=ReviewDecisionType.APPROVE,
        reason="ok",
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        snapshot_hash=report.report_input_snapshot_hash,
        citation_set_hash=report.citation_set_hash,
        release_policy_version="release-v1",
        evaluation_hash=evaluation.evaluation_hash,
        created_at=NOW,
    )
    repository.add(recorded)
    fingerprint = recorded.semantic_fingerprint
    with pytest.raises(ReviewReplayError, match="hard-gated"):
        HumanReviewReplay(sessions).replay(
            report_id=report.report_id, semantic_fingerprint=fingerprint, now=NOW
        )
