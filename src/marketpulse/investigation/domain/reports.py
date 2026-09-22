from __future__ import annotations

from datetime import datetime

from pydantic import Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    BlobReference,
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)
from marketpulse.investigation.domain.enums import (
    AuditActorType,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ReviewDecisionOrigin,
    ReviewDecisionType,
)


class Report(DomainModel):
    """Immutable report version bound to a ReportInputSnapshot.

    Lifecycle status never mutates on this record; the mutable latest-state
    projection lives in ``ReportProjection``.
    """

    report_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    version: int = Field(ge=1)
    report_type: ReportType
    report_input_snapshot_hash: Sha256
    report_hash: Sha256
    claim_set_hash: Sha256
    citation_set_hash: Sha256
    release_policy_version: NonEmptyText
    schema_version: NonEmptyText = "phase5-report-v1"
    created_at: datetime


class ReportProjection(DomainModel):
    """Controlled-mutable latest lifecycle state for a report version."""

    report_id: EntityId
    investigation_id: EntityId
    review_status: ReportReviewStatus
    release_status: ReportReleaseStatus
    active_review_request_id: EntityId | None = None
    latest_evaluation_id: EntityId | None = None
    updated_at: datetime


class ReportSection(DomainModel):
    section_id: EntityId
    report_id: EntityId
    section_type: NonEmptyText
    order_index: int = Field(ge=0)
    content_blob_ref: BlobReference | None = None
    structured_content: dict[str, JsonValue] | None = None
    claim_ids: tuple[EntityId, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def content_is_present(self) -> ReportSection:
        if self.content_blob_ref is None and self.structured_content is None:
            raise ValueError("report section requires blob or structured content")
        return self


class ReviewDecision(DomainModel):
    """Append-only review decision.

    Authentication provenance is stored as immutable values
    (``reviewer_session_public_id``, ``reviewer_config_fingerprint``) with no
    required long-lived FK to the session row, so governance history survives
    ReviewerSession cleanup.
    """

    review_id: EntityId
    report_id: EntityId
    reviewer_id: EntityId
    decision: ReviewDecisionType
    reason: NonEmptyText
    report_version: int = Field(ge=1)
    report_hash: Sha256
    claim_set_hash: Sha256
    release_policy_version: NonEmptyText
    review_request_id: EntityId | None = None
    reviewer_session_public_id: EntityId | None = None
    reviewer_config_fingerprint: Sha256 | None = None
    decision_origin: ReviewDecisionOrigin = ReviewDecisionOrigin.LIVE
    created_at: datetime


class AuditEvent(DomainModel):
    audit_event_id: EntityId
    investigation_id: EntityId
    run_id: EntityId | None = None
    actor_type: AuditActorType
    actor_id: str | None = None
    event_type: NonEmptyText
    target_type: NonEmptyText
    target_id: EntityId
    previous_state: str | None = None
    new_state: str | None = None
    reason: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime
