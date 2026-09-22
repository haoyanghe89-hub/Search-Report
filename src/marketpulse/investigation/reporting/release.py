"""Deterministic release policy for Phase 5 report governance.

``ReportReleasePolicy`` is pure: no model calls, no network, no database
queries. Every input is supplied by the caller and every output is an
immutable ``ReleasePolicyEvaluation`` whose hash covers the full basis.

Frozen rules:
- Any HARD finding yields exactly ``BLOCK / DRAFT / NOT_REQUIRED`` and can
  never be downgraded to a restricted release.
- ``FULL_INVESTIGATION`` may reach ``PUBLISHED``; ``RESTRICTED_INVESTIGATION``
  and ``INVESTIGATION_STATUS`` have a ``RESTRICTED`` ceiling.
- The governance gate (evaluated only when no HARD finding exists) can only
  produce ``REQUIRE_REVIEW / REVIEW_REQUIRED / PENDING``. It never changes
  Claim status.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from pydantic import JsonValue

from marketpulse.investigation.domain.base import DomainModel, EntityId, NonEmptyText, Sha256
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    FindingSeverity,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
)
from marketpulse.investigation.reporting.models import (
    ReleasePolicyEvaluation,
    ReportValidationFinding,
    SnapshotClaim,
)

RELEASE_POLICY_VERSION = "phase5-release-policy-v1"

GOVERNANCE_CLAIM_TYPES = frozenset({ClaimType.ATTRIBUTION, ClaimType.CAUSAL, ClaimType.IMPACT})
GOVERNANCE_IMPORTANCE = frozenset({ClaimImportance.HIGH, ClaimImportance.CRITICAL})

TRIGGER_GOVERNANCE_CLAIM_SCOPE = "GOVERNANCE_CLAIM_SCOPE"
TRIGGER_UNRESOLVED_STATUS_IN_KEY_SECTIONS = "UNRESOLVED_STATUS_IN_KEY_SECTIONS"
TRIGGER_UNRESOLVED_NONBLOCKING_CONFLICTS = "UNRESOLVED_NONBLOCKING_CONFLICTS"
TRIGGER_GOVERNANCE_PROFILE_REQUIRES_REVIEW = "GOVERNANCE_PROFILE_REQUIRES_REVIEW"
TRIGGER_GOVERNANCE_FINDING = "GOVERNANCE_FINDING"


class ReleasePolicyInput(DomainModel):
    """Complete deterministic input set for one release-policy evaluation.

    ``claims`` is the claim summary taken from the report input snapshot
    payload; ``probable_or_disputed_in_key_sections`` flags PROBABLE/DISPUTED
    claims used in executive/conclusion sections;
    ``unresolved_nonblocking_conflicts`` carries the stable keys of
    unresolved non-blocking conflicts.
    """

    report_id: EntityId
    report_type: ReportType
    report_hash: Sha256
    claim_set_hash: Sha256
    citation_set_hash: Sha256
    findings: tuple[ReportValidationFinding, ...] = ()
    claims: tuple[SnapshotClaim, ...] = ()
    probable_or_disputed_in_key_sections: bool = False
    unresolved_nonblocking_conflicts: tuple[NonEmptyText, ...] = ()
    governance_profile_version: NonEmptyText = "governance-profile-v1"
    governance_profile_requires_review: bool = False


class ReportReleasePolicy:
    """Pure deterministic release policy with strict HARD/GOVERNANCE separation."""

    def __init__(self, *, policy_version: str = RELEASE_POLICY_VERSION) -> None:
        self._policy_version = policy_version

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def evaluate(
        self,
        inputs: ReleasePolicyInput,
        *,
        evaluation_id: EntityId,
        created_at: datetime,
    ) -> ReleasePolicyEvaluation:
        hard_findings = tuple(
            finding for finding in inputs.findings if finding.severity is FindingSeverity.HARD
        )
        governance_finding_count = sum(
            1 for finding in inputs.findings if finding.severity is FindingSeverity.GOVERNANCE
        )
        governance_claim_keys = self._governance_claim_keys(inputs)
        triggers: tuple[str, ...] = ()
        if not hard_findings:
            triggers = self._governance_triggers(inputs, governance_claim_keys)

        approval_release_status = (
            ReportReleaseStatus.PUBLISHED
            if inputs.report_type is ReportType.FULL_INVESTIGATION
            else ReportReleaseStatus.RESTRICTED
        )
        if hard_findings:
            decision = ReleaseDecision.BLOCK
            release_status = ReportReleaseStatus.DRAFT
            review_status = ReportReviewStatus.NOT_REQUIRED
        elif triggers:
            decision = ReleaseDecision.REQUIRE_REVIEW
            release_status = ReportReleaseStatus.REVIEW_REQUIRED
            review_status = ReportReviewStatus.PENDING
        elif inputs.report_type is ReportType.FULL_INVESTIGATION:
            decision = ReleaseDecision.PUBLISH
            release_status = ReportReleaseStatus.PUBLISHED
            review_status = ReportReviewStatus.NOT_REQUIRED
        else:
            decision = ReleaseDecision.RESTRICT
            release_status = ReportReleaseStatus.RESTRICTED
            review_status = ReportReviewStatus.NOT_REQUIRED

        hard_codes = cast(list[JsonValue], sorted({finding.code for finding in hard_findings}))
        trigger_list = cast(list[JsonValue], sorted(triggers))
        claim_keys = cast(list[JsonValue], sorted(governance_claim_keys))
        basis: dict[str, JsonValue] = {
            "report_type": inputs.report_type.value,
            "governance_profile_version": inputs.governance_profile_version,
            "hard_finding_codes": hard_codes,
            "governance_triggers": trigger_list,
            "governance_claim_stable_keys": claim_keys,
            "approval_target": {
                "release_status": approval_release_status.value,
                "review_status": ReportReviewStatus.APPROVED.value,
            },
            "rejection_target": {
                "release_status": ReportReleaseStatus.DRAFT.value,
                "review_status": ReportReviewStatus.REJECTED.value,
            },
        }
        return ReleasePolicyEvaluation.build(
            evaluation_id=evaluation_id,
            report_id=inputs.report_id,
            policy_version=self._policy_version,
            decision=decision,
            release_status=release_status,
            review_status=review_status,
            report_hash=inputs.report_hash,
            claim_set_hash=inputs.claim_set_hash,
            citation_set_hash=inputs.citation_set_hash,
            hard_finding_count=len(hard_findings),
            governance_finding_count=governance_finding_count,
            basis=basis,
            created_at=created_at,
        )

    def _governance_triggers(
        self, inputs: ReleasePolicyInput, governance_claim_keys: tuple[str, ...]
    ) -> tuple[str, ...]:
        triggers: set[str] = set()
        if governance_claim_keys:
            triggers.add(TRIGGER_GOVERNANCE_CLAIM_SCOPE)
        if inputs.probable_or_disputed_in_key_sections:
            triggers.add(TRIGGER_UNRESOLVED_STATUS_IN_KEY_SECTIONS)
        if inputs.unresolved_nonblocking_conflicts:
            triggers.add(TRIGGER_UNRESOLVED_NONBLOCKING_CONFLICTS)
        if inputs.governance_profile_requires_review:
            triggers.add(TRIGGER_GOVERNANCE_PROFILE_REQUIRES_REVIEW)
        if any(finding.severity is FindingSeverity.GOVERNANCE for finding in inputs.findings):
            triggers.add(TRIGGER_GOVERNANCE_FINDING)
        return tuple(sorted(triggers))

    @staticmethod
    def _governance_claim_keys(inputs: ReleasePolicyInput) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    claim.stable_key
                    for claim in inputs.claims
                    if claim.claim_type in GOVERNANCE_CLAIM_TYPES
                    and claim.importance in GOVERNANCE_IMPORTANCE
                }
            )
        )
