"""Phase 5.5 human-review replay.

Replay uses a ``RecordedHumanReviewDecision`` matched by exact semantic
fingerprint. It never authenticates, never executes Argon2, never creates or
simulates a session, and never performs real publication: the replay release
ceiling is RESTRICTED. Policy applicability, hash bindings, and allowed-action
validation are all re-executed; decisions and audit events are appended with
``decision_origin=REPLAY``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.enums import (
    AuditActorType,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReviewDecisionOrigin,
    ReviewDecisionType,
)
from marketpulse.investigation.domain.reports import AuditEvent, Report, ReviewDecision
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.review.models import RecordedHumanReviewDecision

REPLAY_RELEASE_CEILING = ReportReleaseStatus.RESTRICTED


class ReviewReplayError(RuntimeError):
    """Replay cannot proceed: fingerprint or policy binding mismatch."""


class ReplayedReviewOutcome:
    def __init__(
        self,
        *,
        review_id: str,
        release_status: ReportReleaseStatus,
        would_release_status: ReportReleaseStatus,
        decision: ReviewDecisionType,
    ) -> None:
        self.review_id = review_id
        self.release_status = release_status
        self.would_release_status = would_release_status
        self.decision = decision


def record_for_replay(
    session: Session,
    repository: InvestigationRepository,
    *,
    decision: ReviewDecision,
    request_evaluation_hash: str,
    snapshot_hash: str,
    citation_set_hash: str,
    now: datetime,
) -> RecordedHumanReviewDecision:
    """Persist the replayable semantic fingerprint of a live review decision."""
    recorded = RecordedHumanReviewDecision.build(
        recorded_id=f"REC-{uuid.uuid4().hex}",
        reviewer_id=decision.reviewer_id,
        decision=decision.decision,
        reason=decision.reason,
        report_hash=decision.report_hash,
        claim_set_hash=decision.claim_set_hash,
        snapshot_hash=snapshot_hash,
        citation_set_hash=citation_set_hash,
        release_policy_version=decision.release_policy_version,
        evaluation_hash=request_evaluation_hash,
        created_at=now,
    )
    repository.add_in_session(session, recorded)
    return recorded


class HumanReviewReplay:
    """Re-executes a recorded human review decision without authentication."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._repository = InvestigationRepository(sessions)
        self._governance = ReportGovernanceRepository(sessions)

    def replay(
        self,
        *,
        report_id: str,
        semantic_fingerprint: str,
        now: datetime,
    ) -> ReplayedReviewOutcome:
        with self._sessions.begin() as session:
            recorded = self._governance.recorded_decision_by_fingerprint_in_session(
                session, semantic_fingerprint
            )
            if recorded is None:
                raise ReviewReplayError("no recorded decision matches the fingerprint")
            try:
                report = self._repository.get_in_session(session, Report, report_id)
            except KeyError as exc:
                raise ReviewReplayError(f"report {report_id} missing") from exc
            evaluation = self._governance.latest_evaluation_in_session(session, report_id)
            if evaluation is None:
                raise ReviewReplayError(f"report {report_id} has no evaluation")
            if evaluation.decision is ReleaseDecision.BLOCK:
                raise ReviewReplayError("hard-gated report cannot be reviewed, even in replay")

            mismatches: list[str] = []
            if recorded.report_hash != report.report_hash:
                mismatches.append("report_hash")
            if recorded.claim_set_hash != report.claim_set_hash:
                mismatches.append("claim_set_hash")
            if recorded.snapshot_hash != report.report_input_snapshot_hash:
                mismatches.append("snapshot_hash")
            if recorded.citation_set_hash != report.citation_set_hash:
                mismatches.append("citation_set_hash")
            if recorded.evaluation_hash != evaluation.evaluation_hash:
                mismatches.append("evaluation_hash")
            if recorded.release_policy_version != report.release_policy_version:
                mismatches.append("release_policy_version")
            if mismatches:
                raise ReviewReplayError(
                    "replay fingerprint mismatch: " + ", ".join(sorted(mismatches))
                )

            would_release, review_status = self._target(recorded, evaluation)
            release_status = would_release
            if release_status is ReportReleaseStatus.PUBLISHED:
                release_status = REPLAY_RELEASE_CEILING

            review_id = f"REV-REPLAY-{uuid.uuid4().hex}"
            self._repository.add_in_session(
                session,
                ReviewDecision(
                    review_id=review_id,
                    report_id=report.report_id,
                    reviewer_id=recorded.reviewer_id,
                    decision=recorded.decision,
                    reason=recorded.reason,
                    report_version=report.version,
                    report_hash=report.report_hash,
                    claim_set_hash=report.claim_set_hash,
                    release_policy_version=report.release_policy_version,
                    decision_origin=ReviewDecisionOrigin.REPLAY,
                    created_at=now,
                ),
            )
            projection = self._governance.get_projection_in_session(session, report_id)
            if projection is not None:
                self._governance.save_projection_in_session(
                    session,
                    projection.model_copy(
                        update={
                            "release_status": release_status,
                            "review_status": review_status,
                            "updated_at": now,
                        }
                    ),
                )
            self._repository.add_in_session(
                session,
                AuditEvent(
                    audit_event_id=f"AUD-{uuid.uuid4().hex}",
                    investigation_id=report.investigation_id,
                    run_id=report.run_id,
                    actor_type=AuditActorType.HUMAN,
                    actor_id=recorded.reviewer_id,
                    event_type="REVIEW_DECISION_REPLAYED",
                    target_type="Report",
                    target_id=report.report_id,
                    new_state=f"{release_status.value}:{review_status.value}",
                    reason=recorded.reason,
                    metadata={
                        "decision": recorded.decision.value,
                        "would_release_status": would_release.value,
                        "replay_ceiling": REPLAY_RELEASE_CEILING.value,
                    },
                    created_at=now,
                ),
            )
            return ReplayedReviewOutcome(
                review_id=review_id,
                release_status=release_status,
                would_release_status=would_release,
                decision=recorded.decision,
            )

    @staticmethod
    def _target(
        recorded: RecordedHumanReviewDecision, evaluation: object
    ) -> tuple[ReportReleaseStatus, ReportReviewStatus]:
        if recorded.decision is ReviewDecisionType.APPROVE:
            approval = getattr(evaluation, "basis", {}).get("approval_target")
            raw = approval.get("release_status") if isinstance(approval, dict) else None
            target = ReportReleaseStatus(str(raw or ReportReleaseStatus.RESTRICTED.value))
            return target, ReportReviewStatus.APPROVED
        if recorded.decision is ReviewDecisionType.REJECT:
            return ReportReleaseStatus.DRAFT, ReportReviewStatus.REJECTED
        return ReportReleaseStatus.DRAFT, ReportReviewStatus.CHANGES_REQUESTED
