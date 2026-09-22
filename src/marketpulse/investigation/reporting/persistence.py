"""Typed repository for Phase 5 report governance persistence.

Append-only entities (snapshots, report versions, citations, findings,
evaluations, review requests, research requests, recorded decisions) are
inserted through ``InvestigationRepository`` and guarded by database triggers.
This repository adds typed lookups plus the controlled-mutable state operations
(projections, reviewer sessions, auth state, rate buckets, idempotency).
Callers own transaction boundaries via the ``*_in_session`` methods.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.base import DomainModel
from marketpulse.investigation.domain.reports import ReportProjection
from marketpulse.investigation.persistence.models import (
    CitationRow,
    RecordedHumanReviewDecisionRow,
    ReleasePolicyEvaluationRow,
    ReportInputSnapshotRow,
    ReportProjectionRow,
    ReportValidationFindingRow,
    ReviewDecisionRow,
    ReviewerAuthStateRow,
    ReviewerSessionRow,
    ReviewIdempotencyRow,
    ReviewRateBucketRow,
    ReviewRequestRow,
)
from marketpulse.investigation.reporting.models import (
    Citation,
    ReleasePolicyEvaluation,
    ReportInputSnapshot,
    ReportValidationFinding,
)
from marketpulse.investigation.review.models import (
    RecordedHumanReviewDecision,
    ReviewerAuthState,
    ReviewerSession,
    ReviewIdempotencyRecord,
    ReviewRateBucket,
    ReviewRequest,
)


class ReportGovernanceRepository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    # -- typed lookups over append-only rows ---------------------------------

    def snapshot_by_hash_in_session(
        self, session: Session, snapshot_hash: str
    ) -> ReportInputSnapshot | None:
        row = session.scalar(
            select(ReportInputSnapshotRow).where(
                ReportInputSnapshotRow.snapshot_hash == snapshot_hash
            )
        )
        return _model(ReportInputSnapshot, row)

    def latest_snapshot_for_run_in_session(
        self, session: Session, run_id: str
    ) -> ReportInputSnapshot | None:
        row = session.scalar(
            select(ReportInputSnapshotRow)
            .where(ReportInputSnapshotRow.run_id == run_id)
            .order_by(ReportInputSnapshotRow.assembled_at.desc())
            .limit(1)
        )
        return _model(ReportInputSnapshot, row)

    def citations_for_report_in_session(self, session: Session, report_id: str) -> list[Citation]:
        rows = session.scalars(
            select(CitationRow)
            .where(CitationRow.report_id == report_id)
            .order_by(CitationRow.display_ordinal)
        ).all()
        return [Citation.model_validate(_row_dict(row)) for row in rows]

    def findings_for_report_in_session(
        self, session: Session, report_id: str
    ) -> list[ReportValidationFinding]:
        rows = session.scalars(
            select(ReportValidationFindingRow)
            .where(ReportValidationFindingRow.report_id == report_id)
            .order_by(ReportValidationFindingRow.created_at, ReportValidationFindingRow.finding_id)
        ).all()
        return [ReportValidationFinding.model_validate(_row_dict(row)) for row in rows]

    def latest_evaluation_in_session(
        self, session: Session, report_id: str
    ) -> ReleasePolicyEvaluation | None:
        row = session.scalar(
            select(ReleasePolicyEvaluationRow)
            .where(ReleasePolicyEvaluationRow.report_id == report_id)
            .order_by(ReleasePolicyEvaluationRow.created_at.desc())
            .limit(1)
        )
        return _model(ReleasePolicyEvaluation, row)

    def pending_request_for_report_in_session(
        self, session: Session, report_id: str, now: datetime
    ) -> ReviewRequest | None:
        """Latest request with no recorded decision that has not yet expired."""
        rows = session.scalars(
            select(ReviewRequestRow)
            .where(ReviewRequestRow.report_id == report_id)
            .order_by(ReviewRequestRow.created_at.desc())
        ).all()
        for row in rows:
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                continue
            decided = session.scalar(
                select(ReviewDecisionRow.review_id)
                .where(ReviewDecisionRow.review_request_id == row.request_id)
                .limit(1)
            )
            if decided is None:
                return ReviewRequest.model_validate(_row_dict(row))
        return None

    # -- controlled-mutable state ---------------------------------------------

    def get_projection_in_session(
        self, session: Session, report_id: str
    ) -> ReportProjection | None:
        return _model(ReportProjection, session.get(ReportProjectionRow, report_id))

    def save_projection_in_session(self, session: Session, projection: ReportProjection) -> None:
        row = session.get(ReportProjectionRow, projection.report_id)
        values = _row_dict_from_model(projection)
        if row is None:
            session.add(ReportProjectionRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.flush()

    def get_auth_state_in_session(
        self, session: Session, reviewer_id: str
    ) -> ReviewerAuthState | None:
        return _model(ReviewerAuthState, session.get(ReviewerAuthStateRow, reviewer_id))

    def save_auth_state_in_session(self, session: Session, state: ReviewerAuthState) -> None:
        row = session.get(ReviewerAuthStateRow, state.reviewer_id)
        values = _row_dict_from_model(state)
        if row is None:
            session.add(ReviewerAuthStateRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.flush()

    def session_by_token_hash_in_session(
        self, session: Session, token_hash: str
    ) -> ReviewerSession | None:
        row = session.scalar(
            select(ReviewerSessionRow).where(ReviewerSessionRow.token_hash == token_hash)
        )
        return _model(ReviewerSession, row)

    def save_session_in_session(self, session: Session, reviewer_session: ReviewerSession) -> None:
        row = session.get(ReviewerSessionRow, reviewer_session.session_public_id)
        values = _row_dict_from_model(reviewer_session)
        if row is None:
            session.add(ReviewerSessionRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.flush()

    def get_rate_bucket_in_session(
        self, session: Session, bucket_fingerprint: str
    ) -> ReviewRateBucket | None:
        return _model(ReviewRateBucket, session.get(ReviewRateBucketRow, bucket_fingerprint))

    def save_rate_bucket_in_session(self, session: Session, bucket: ReviewRateBucket) -> None:
        row = session.get(ReviewRateBucketRow, bucket.bucket_fingerprint)
        values = _row_dict_from_model(bucket)
        if row is None:
            session.add(ReviewRateBucketRow(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        session.flush()

    def get_idempotency_in_session(
        self, session: Session, idempotency_key: str
    ) -> ReviewIdempotencyRecord | None:
        return _model(ReviewIdempotencyRecord, session.get(ReviewIdempotencyRow, idempotency_key))

    def recorded_decision_by_fingerprint_in_session(
        self, session: Session, semantic_fingerprint: str
    ) -> RecordedHumanReviewDecision | None:
        row = session.scalar(
            select(RecordedHumanReviewDecisionRow).where(
                RecordedHumanReviewDecisionRow.semantic_fingerprint == semantic_fingerprint
            )
        )
        return _model(RecordedHumanReviewDecision, row)


T = TypeVar("T", bound=DomainModel)


def _model(model_type: type[T], row: object | None) -> T | None:
    if row is None:
        return None
    return model_type.model_validate(_row_dict(row))


def _row_dict(row: object) -> dict[str, object]:
    table = row.__table__  # type: ignore[attr-defined]
    return {column.key: getattr(row, column.key) for column in table.columns}


def _row_dict_from_model(model: DomainModel) -> dict[str, object]:
    return dict(model.model_dump())
