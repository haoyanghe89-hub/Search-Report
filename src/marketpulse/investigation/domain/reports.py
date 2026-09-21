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
    ReviewDecisionType,
)


class Report(DomainModel):
    report_id: EntityId
    investigation_id: EntityId
    run_id: EntityId
    version: int = Field(ge=1)
    report_type: ReportType
    review_status: ReportReviewStatus
    release_status: ReportReleaseStatus
    report_hash: Sha256
    claim_set_hash: Sha256
    release_policy_version: NonEmptyText
    created_at: datetime
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
    review_id: EntityId
    report_id: EntityId
    reviewer_id: EntityId
    decision: ReviewDecisionType
    reason: NonEmptyText
    report_version: int = Field(ge=1)
    report_hash: Sha256
    claim_set_hash: Sha256
    release_policy_version: NonEmptyText
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
