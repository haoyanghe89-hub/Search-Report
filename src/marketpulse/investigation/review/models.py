"""Domain models for Phase 5 release governance and human review.

Append-only: ReviewRequest, ReviewResearchRequest, RecordedHumanReviewDecision
(plus ReviewDecision/AuditEvent in ``domain.reports``).
Controlled mutable: ReviewerSession, ReviewerAuthState, ReviewRateBucket,
ReviewIdempotencyRecord.

Security invariants: the database stores only Argon2id password-hash
configuration fingerprints and domain-separated session token hashes — never
plaintext passwords, password-hash copies, raw session tokens, or raw client
addresses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import Field, JsonValue

from marketpulse.investigation.domain.base import (
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)
from marketpulse.investigation.domain.enums import ReviewDecisionType
from marketpulse.investigation.reporting.hashing import canonical_hash

REVIEW_FINGERPRINT_DOMAIN = "phase5-human-review-decision-v1"


class ReviewRequest(DomainModel):
    """Immutable governance review request with exact version bindings.

    A request is never mutated: outcomes are recorded as ReviewDecision rows
    referencing ``request_id``; expiry is derived from ``expires_at``; a new
    cycle is a new request.
    """

    request_id: EntityId
    report_id: EntityId
    report_version: int = Field(ge=1)
    snapshot_hash: Sha256
    claim_set_hash: Sha256
    citation_set_hash: Sha256
    report_hash: Sha256
    evaluation_hash: Sha256
    evaluation_id: EntityId
    validator_version: NonEmptyText
    policy_version: NonEmptyText
    trigger_reason: NonEmptyText
    created_at: datetime
    expires_at: datetime


class ReviewerSession(DomainModel):
    """Server-side opaque session. Only the token hash is persisted."""

    session_public_id: EntityId
    reviewer_id: NonEmptyText
    token_hash: Sha256
    reviewer_config_fingerprint: Sha256
    generation: int = Field(ge=1)
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class ReviewerAuthState(DomainModel):
    """Singleton mutable auth pointer enforcing a single active session."""

    reviewer_id: NonEmptyText
    active_session_public_id: EntityId | None = None
    active_generation: int = Field(ge=0)
    config_fingerprint: Sha256
    updated_at: datetime


class ReviewRateBucket(DomainModel):
    """Login rate-limit bucket keyed by HMAC client fingerprint, never raw IP."""

    bucket_fingerprint: Sha256
    failure_count: int = Field(ge=0)
    window_started_at: datetime
    locked_until: datetime | None = None
    updated_at: datetime


class ReviewResearchRequest(DomainModel):
    """Append-only follow-up research request created by REQUEST_MORE_RESEARCH."""

    request_id: EntityId
    review_id: EntityId
    report_id: EntityId
    reason: NonEmptyText
    follow_up_run_id: EntityId | None = None
    created_at: datetime


class ReviewIdempotencyRecord(DomainModel):
    """Stored response for an idempotency key so retried mutations replay."""

    idempotency_key: NonEmptyText
    report_id: EntityId
    reviewer_id: NonEmptyText
    decision: ReviewDecisionType
    response_payload: dict[str, JsonValue]
    created_at: datetime


class RecordedHumanReviewDecision(DomainModel):
    """Replay-safe recording of a human review decision.

    Replay matches on the exact semantic fingerprint; it never authenticates,
    never touches sessions, and is capped at a RESTRICTED release ceiling.
    """

    recorded_id: EntityId
    reviewer_id: NonEmptyText
    decision: ReviewDecisionType
    reason: NonEmptyText
    report_hash: Sha256
    claim_set_hash: Sha256
    snapshot_hash: Sha256
    citation_set_hash: Sha256
    release_policy_version: NonEmptyText
    evaluation_hash: Sha256
    semantic_fingerprint: Sha256
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        recorded_id: EntityId,
        reviewer_id: NonEmptyText,
        decision: ReviewDecisionType,
        reason: NonEmptyText,
        report_hash: Sha256,
        claim_set_hash: Sha256,
        snapshot_hash: Sha256,
        citation_set_hash: Sha256,
        release_policy_version: NonEmptyText,
        evaluation_hash: Sha256,
        created_at: datetime,
    ) -> Self:
        fingerprint = canonical_hash(
            REVIEW_FINGERPRINT_DOMAIN,
            {
                "reviewer_id": reviewer_id,
                "decision": decision,
                "reason": reason,
                "report_hash": report_hash,
                "claim_set_hash": claim_set_hash,
                "snapshot_hash": snapshot_hash,
                "citation_set_hash": citation_set_hash,
                "release_policy_version": release_policy_version,
                "evaluation_hash": evaluation_hash,
            },
        )
        return cls(
            recorded_id=recorded_id,
            reviewer_id=reviewer_id,
            decision=decision,
            reason=reason,
            report_hash=report_hash,
            claim_set_hash=claim_set_hash,
            snapshot_hash=snapshot_hash,
            citation_set_hash=citation_set_hash,
            release_policy_version=release_policy_version,
            evaluation_hash=evaluation_hash,
            semantic_fingerprint=fingerprint,
            created_at=created_at,
        )
