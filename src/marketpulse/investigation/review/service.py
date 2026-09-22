"""Human review lifecycle service for Phase 5 report governance.

A review decision is applicable only while the current report hash, claim-set
hash, citation-set hash, evaluation hash, and policy version match the
immutable ``ReviewRequest`` bindings exactly; otherwise the cycle is stale and
rejected. APPROVE applies only the policy-precomputed approval target, REJECT
the precomputed rejection target (``DRAFT / REJECTED``), and
REQUEST_MORE_RESEARCH appends a ``ReviewResearchRequest`` and returns the
follow-up investigation need (the follow-up run is created elsewhere).

Every successful mutation writes the ``ReviewDecision``, an ``AuditEvent``,
the updated ``ReportProjection``, and optionally a ``ReviewResearchRequest``
atomically in one transaction; any failure rolls the whole mutation back. A
best-effort failed-attempt audit may then be written in a separate
transaction.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.base import DomainModel, EntityId, NonEmptyText
from marketpulse.investigation.domain.enums import (
    AuditActorType,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ReviewDecisionOrigin,
    ReviewDecisionType,
)
from marketpulse.investigation.domain.reports import (
    AuditEvent,
    Report,
    ReportProjection,
    ReviewDecision,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.models import ReleasePolicyEvaluation
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.review.models import (
    ReviewIdempotencyRecord,
    ReviewRequest,
    ReviewResearchRequest,
)

logger = logging.getLogger(__name__)


class ReviewError(Exception):
    """Base class for review lifecycle failures."""


class ReviewReportNotFoundError(ReviewError):
    """The target report does not exist."""


class ReviewCycleNotOpenError(ReviewError):
    """No unexpired, undecided review request exists for the report."""


class ReviewCycleAlreadyOpenError(ReviewError):
    """An unexpired, undecided review request already exists for the report."""


class ReviewHardGateBlockedError(ReviewError):
    """The latest evaluation is BLOCK; human review can never override it."""


class StaleReviewBindingError(ReviewError):
    """Current report state no longer matches the review request bindings."""

    def __init__(self, mismatches: tuple[str, ...]) -> None:
        super().__init__(f"stale review cycle; mismatched bindings: {', '.join(mismatches)}")
        self.mismatches = mismatches


class ReviewIdempotencyConflictError(ReviewError):
    """The idempotency key was already used for a different mutation."""


class ReviewerIdentity(DomainModel):
    """Reviewer identity injected from an authenticated session or replay."""

    reviewer_id: NonEmptyText
    session_public_id: EntityId | None = None
    config_fingerprint: NonEmptyText | None = None
    origin: ReviewDecisionOrigin = ReviewDecisionOrigin.LIVE


class FollowUpResearchNeed(DomainModel):
    """Parameters for the follow-up InvestigationRun (created elsewhere)."""

    research_request_id: EntityId
    report_id: EntityId
    reason: NonEmptyText
    origin_run_id: EntityId
    origin_review_request_id: EntityId


class ReviewOutcome(DomainModel):
    """Result of a recorded review decision; stored for idempotent replay."""

    review_id: EntityId
    report_id: EntityId
    decision: ReviewDecisionType
    release_status: ReportReleaseStatus
    review_status: ReportReviewStatus
    follow_up: FollowUpResearchNeed | None = None


class ReportReviewService:
    """Review-cycle generation and decision recording over the report graph."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._repository = InvestigationRepository(sessions)
        self._governance = ReportGovernanceRepository(sessions)

    def open_review_request(
        self,
        *,
        report_id: str,
        validator_version: str,
        trigger_reason: str,
        now: datetime,
        expires_at: datetime,
        request_id: str | None = None,
    ) -> ReviewRequest:
        """Open an immutable review cycle bound to the latest evaluation.

        Requires the latest evaluation to be ``REQUIRE_REVIEW`` and its hashes
        to match the current report; refuses to open a second pending cycle.
        """
        with self._sessions.begin() as session:
            report = self._load_report(session, report_id)
            evaluation = self._governance.latest_evaluation_in_session(session, report_id)
            if evaluation is None:
                raise ReviewCycleNotOpenError(f"report {report_id} has no release evaluation")
            if evaluation.decision is not ReleaseDecision.REQUIRE_REVIEW:
                raise ReviewCycleNotOpenError(
                    f"report {report_id} evaluation decision is {evaluation.decision.value}"
                )
            mismatches = self._evaluation_mismatches(report, evaluation)
            if mismatches:
                raise StaleReviewBindingError(mismatches)
            if (
                self._governance.pending_request_for_report_in_session(session, report_id, now)
                is not None
            ):
                raise ReviewCycleAlreadyOpenError(
                    f"report {report_id} already has a pending review request"
                )
            request = ReviewRequest(
                request_id=request_id or f"RRQ-{uuid.uuid4().hex}",
                report_id=report.report_id,
                report_version=report.version,
                snapshot_hash=report.report_input_snapshot_hash,
                claim_set_hash=report.claim_set_hash,
                citation_set_hash=report.citation_set_hash,
                report_hash=report.report_hash,
                evaluation_hash=evaluation.evaluation_hash,
                evaluation_id=evaluation.evaluation_id,
                validator_version=validator_version,
                policy_version=evaluation.policy_version,
                trigger_reason=trigger_reason,
                created_at=now,
                expires_at=expires_at,
            )
            self._repository.add_in_session(session, request)
            projection = self._governance.get_projection_in_session(session, report_id)
            base = projection or self._initial_projection(report, evaluation, now)
            self._governance.save_projection_in_session(
                session,
                base.model_copy(
                    update={
                        "release_status": ReportReleaseStatus.REVIEW_REQUIRED,
                        "review_status": ReportReviewStatus.PENDING,
                        "active_review_request_id": request.request_id,
                        "latest_evaluation_id": evaluation.evaluation_id,
                        "updated_at": now,
                    }
                ),
            )
        return request

    def record_decision(
        self,
        *,
        report_id: str,
        decision: ReviewDecisionType,
        reason: str,
        reviewer: ReviewerIdentity,
        now: datetime,
        review_id: str | None = None,
        research_request_id: str | None = None,
        audit_event_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ReviewOutcome:
        """Record APPROVE/REJECT/REQUEST_MORE_RESEARCH atomically.

        Writes the decision, audit event, projection update, and optional
        research request in one transaction; any failure rolls back everything
        before a best-effort failure audit is attempted separately.
        """
        try:
            return self._record_decision_once(
                report_id=report_id,
                decision=decision,
                reason=reason,
                reviewer=reviewer,
                now=now,
                review_id=review_id,
                research_request_id=research_request_id,
                audit_event_id=audit_event_id,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            if idempotency_key is not None:
                with self._sessions() as session:
                    existing = self._governance.get_idempotency_in_session(session, idempotency_key)
                if existing is not None:
                    return ReviewOutcome.model_validate(existing.response_payload)
            raise
        except ReviewError as error:
            self._audit_failure_best_effort(
                report_id=report_id, reviewer=reviewer, decision=decision, error=error, now=now
            )
            raise

    def _record_decision_once(
        self,
        *,
        report_id: str,
        decision: ReviewDecisionType,
        reason: str,
        reviewer: ReviewerIdentity,
        now: datetime,
        review_id: str | None,
        research_request_id: str | None,
        audit_event_id: str | None,
        idempotency_key: str | None,
    ) -> ReviewOutcome:
        with self._sessions.begin() as session:
            if idempotency_key is not None:
                existing = self._governance.get_idempotency_in_session(session, idempotency_key)
                if existing is not None:
                    if (
                        existing.report_id != report_id
                        or existing.reviewer_id != reviewer.reviewer_id
                        or existing.decision is not decision
                    ):
                        raise ReviewIdempotencyConflictError(
                            f"idempotency key {idempotency_key!r} was used for another mutation"
                        )
                    return ReviewOutcome.model_validate(existing.response_payload)

            report = self._load_report(session, report_id)
            evaluation = self._governance.latest_evaluation_in_session(session, report_id)
            if evaluation is None:
                raise ReviewCycleNotOpenError(f"report {report_id} has no release evaluation")
            if evaluation.decision is ReleaseDecision.BLOCK:
                raise ReviewHardGateBlockedError(
                    f"report {report_id} is hard-gated; review cannot override BLOCK"
                )
            request = self._governance.pending_request_for_report_in_session(
                session, report_id, now
            )
            if request is None:
                raise ReviewCycleNotOpenError(
                    f"report {report_id} has no open review request (missing, expired, or decided)"
                )
            mismatches = self._binding_mismatches(report, request)
            if request.evaluation_hash != evaluation.evaluation_hash:
                mismatches.append("evaluation_hash")
            if request.evaluation_id != evaluation.evaluation_id:
                mismatches.append("evaluation_id")
            if request.policy_version != evaluation.policy_version:
                mismatches.append("policy_version")
            if mismatches:
                raise StaleReviewBindingError(tuple(sorted(mismatches)))

            target_release, target_review = self._decision_target(report, evaluation, decision)
            resolved_review_id = review_id or f"REV-{uuid.uuid4().hex}"
            review_decision = ReviewDecision(
                review_id=resolved_review_id,
                report_id=report.report_id,
                reviewer_id=reviewer.reviewer_id,
                decision=decision,
                reason=reason,
                report_version=report.version,
                report_hash=report.report_hash,
                claim_set_hash=report.claim_set_hash,
                release_policy_version=report.release_policy_version,
                review_request_id=request.request_id,
                reviewer_session_public_id=reviewer.session_public_id,
                reviewer_config_fingerprint=reviewer.config_fingerprint,
                decision_origin=reviewer.origin,
                created_at=now,
            )
            self._repository.add_in_session(session, review_decision)

            follow_up: FollowUpResearchNeed | None = None
            if decision is ReviewDecisionType.REQUEST_MORE_RESEARCH:
                research_request = ReviewResearchRequest(
                    request_id=research_request_id or f"RRR-{uuid.uuid4().hex}",
                    review_id=resolved_review_id,
                    report_id=report.report_id,
                    reason=reason,
                    created_at=now,
                )
                self._repository.add_in_session(session, research_request)
                follow_up = FollowUpResearchNeed(
                    research_request_id=research_request.request_id,
                    report_id=report.report_id,
                    reason=reason,
                    origin_run_id=report.run_id,
                    origin_review_request_id=request.request_id,
                )

            projection = self._governance.get_projection_in_session(session, report_id)
            base = projection or self._initial_projection(report, evaluation, now)
            previous_state = f"{base.release_status.value}:{base.review_status.value}"
            self._governance.save_projection_in_session(
                session,
                base.model_copy(
                    update={
                        "release_status": target_release,
                        "review_status": target_review,
                        "active_review_request_id": None,
                        "latest_evaluation_id": evaluation.evaluation_id,
                        "updated_at": now,
                    }
                ),
            )
            self._repository.add_in_session(
                session,
                AuditEvent(
                    audit_event_id=audit_event_id or f"AUD-{uuid.uuid4().hex}",
                    investigation_id=report.investigation_id,
                    run_id=report.run_id,
                    actor_type=AuditActorType.HUMAN,
                    actor_id=reviewer.reviewer_id,
                    event_type="REVIEW_DECISION_RECORDED",
                    target_type="Report",
                    target_id=report.report_id,
                    previous_state=previous_state,
                    new_state=f"{target_release.value}:{target_review.value}",
                    reason=reason,
                    metadata={
                        "decision": decision.value,
                        "review_id": resolved_review_id,
                        "review_request_id": request.request_id,
                        "decision_origin": reviewer.origin.value,
                    },
                    created_at=now,
                ),
            )
            if reviewer.origin is ReviewDecisionOrigin.LIVE:
                from marketpulse.investigation.review.replay import record_for_replay

                record_for_replay(
                    session,
                    self._repository,
                    decision=review_decision,
                    request_evaluation_hash=request.evaluation_hash,
                    snapshot_hash=report.report_input_snapshot_hash,
                    citation_set_hash=report.citation_set_hash,
                    now=now,
                )
            outcome = ReviewOutcome(
                review_id=resolved_review_id,
                report_id=report.report_id,
                decision=decision,
                release_status=target_release,
                review_status=target_review,
                follow_up=follow_up,
            )
            if idempotency_key is not None:
                self._repository.add_in_session(
                    session,
                    ReviewIdempotencyRecord(
                        idempotency_key=idempotency_key,
                        report_id=report.report_id,
                        reviewer_id=reviewer.reviewer_id,
                        decision=decision,
                        response_payload=outcome.model_dump(mode="json"),
                        created_at=now,
                    ),
                )
            return outcome

    @staticmethod
    def _decision_target(
        report: Report, evaluation: ReleasePolicyEvaluation, decision: ReviewDecisionType
    ) -> tuple[ReportReleaseStatus, ReportReviewStatus]:
        if decision is ReviewDecisionType.APPROVE:
            approval = evaluation.basis.get("approval_target")
            raw = approval.get("release_status") if isinstance(approval, dict) else None
            target_release = ReportReleaseStatus(str(raw or ReportReleaseStatus.RESTRICTED.value))
            if (
                report.report_type is not ReportType.FULL_INVESTIGATION
                and target_release is ReportReleaseStatus.PUBLISHED
            ):
                target_release = ReportReleaseStatus.RESTRICTED
            return target_release, ReportReviewStatus.APPROVED
        if decision is ReviewDecisionType.REJECT:
            return ReportReleaseStatus.DRAFT, ReportReviewStatus.REJECTED
        return ReportReleaseStatus.DRAFT, ReportReviewStatus.CHANGES_REQUESTED

    def _load_report(self, session: Session, report_id: str) -> Report:
        try:
            return self._repository.get_in_session(session, Report, report_id)
        except KeyError:
            raise ReviewReportNotFoundError(f"report {report_id} does not exist") from None

    @staticmethod
    def _initial_projection(
        report: Report, evaluation: ReleasePolicyEvaluation, now: datetime
    ) -> ReportProjection:
        return ReportProjection(
            report_id=report.report_id,
            investigation_id=report.investigation_id,
            review_status=evaluation.review_status,
            release_status=evaluation.release_status,
            latest_evaluation_id=evaluation.evaluation_id,
            updated_at=now,
        )

    @staticmethod
    def _binding_mismatches(report: Report, request: ReviewRequest) -> list[str]:
        mismatches: list[str] = []
        if request.report_hash != report.report_hash:
            mismatches.append("report_hash")
        if request.claim_set_hash != report.claim_set_hash:
            mismatches.append("claim_set_hash")
        if request.citation_set_hash != report.citation_set_hash:
            mismatches.append("citation_set_hash")
        if request.snapshot_hash != report.report_input_snapshot_hash:
            mismatches.append("snapshot_hash")
        if request.policy_version != report.release_policy_version:
            mismatches.append("report_policy_version")
        return mismatches

    @staticmethod
    def _evaluation_mismatches(
        report: Report, evaluation: ReleasePolicyEvaluation
    ) -> tuple[str, ...]:
        mismatches: list[str] = []
        if evaluation.report_hash != report.report_hash:
            mismatches.append("report_hash")
        if evaluation.claim_set_hash != report.claim_set_hash:
            mismatches.append("claim_set_hash")
        if evaluation.citation_set_hash != report.citation_set_hash:
            mismatches.append("citation_set_hash")
        if evaluation.policy_version != report.release_policy_version:
            mismatches.append("policy_version")
        return tuple(mismatches)

    def _audit_failure_best_effort(
        self,
        *,
        report_id: str,
        reviewer: ReviewerIdentity,
        decision: ReviewDecisionType,
        error: ReviewError,
        now: datetime,
    ) -> None:
        try:
            with self._sessions.begin() as session:
                report = self._repository.get_in_session(session, Report, report_id)
                self._repository.add_in_session(
                    session,
                    AuditEvent(
                        audit_event_id=f"AUD-{uuid.uuid4().hex}",
                        investigation_id=report.investigation_id,
                        run_id=report.run_id,
                        actor_type=AuditActorType.HUMAN,
                        actor_id=reviewer.reviewer_id,
                        event_type="REVIEW_DECISION_FAILED",
                        target_type="Report",
                        target_id=report_id,
                        reason=type(error).__name__,
                        metadata={
                            "decision": decision.value,
                            "error": type(error).__name__,
                            "decision_origin": reviewer.origin.value,
                        },
                        created_at=now,
                    ),
                )
        except Exception:
            logger.warning(
                "failed to persist review failure audit for report %s", report_id, exc_info=True
            )
