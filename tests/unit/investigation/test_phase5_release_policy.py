from __future__ import annotations

from datetime import UTC, datetime

from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    FindingSeverity,
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
    ReportType,
    ReportValidatorKind,
    ValidationStatus,
)
from marketpulse.investigation.reporting.models import (
    ReportValidationFinding,
    SnapshotClaim,
)
from marketpulse.investigation.reporting.release import (
    ReleasePolicyInput,
    ReportReleasePolicy,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _finding(severity: FindingSeverity, code: str = "SOME_CODE") -> ReportValidationFinding:
    return ReportValidationFinding(
        finding_id=f"FND-{code}",
        report_id="R-1",
        validator=ReportValidatorKind.REPORT,
        severity=severity,
        code=code,
        detail="detail",
        validator_version="report-validator-v1",
        created_at=NOW,
    )


def _claim(claim_type: ClaimType, importance: ClaimImportance) -> SnapshotClaim:
    return SnapshotClaim(
        stable_key=f"claim:{claim_type.value}",
        semantic_hash=HASH_A,
        statement="statement",
        claim_type=claim_type,
        validation_status=ValidationStatus.VERIFIED,
        confidence=0.9,
        validation_semantic_hash=HASH_B,
        importance=importance,
        is_critical=False,
    )


def _inputs(**overrides: object) -> ReleasePolicyInput:
    base = {
        "report_id": "R-1",
        "report_type": ReportType.FULL_INVESTIGATION,
        "report_hash": HASH_A,
        "claim_set_hash": HASH_B,
        "citation_set_hash": HASH_C,
    }
    base.update(overrides)
    return ReleasePolicyInput(**base)  # type: ignore[arg-type]


def _evaluate(inputs: ReleasePolicyInput):
    return ReportReleasePolicy().evaluate(inputs, evaluation_id="EVA-1", created_at=NOW)


def test_hard_finding_blocks_everything() -> None:
    for report_type in ReportType:
        evaluation = _evaluate(
            _inputs(report_type=report_type, findings=(_finding(FindingSeverity.HARD),))
        )
        assert evaluation.decision is ReleaseDecision.BLOCK
        assert evaluation.release_status is ReportReleaseStatus.DRAFT
        assert evaluation.review_status is ReportReviewStatus.NOT_REQUIRED
        assert evaluation.hard_finding_count == 1


def test_clean_full_report_publishes() -> None:
    evaluation = _evaluate(_inputs())
    assert evaluation.decision is ReleaseDecision.PUBLISH
    assert evaluation.release_status is ReportReleaseStatus.PUBLISHED
    assert evaluation.review_status is ReportReviewStatus.NOT_REQUIRED


def test_restricted_and_status_have_restricted_ceiling() -> None:
    for report_type in (ReportType.RESTRICTED_INVESTIGATION, ReportType.INVESTIGATION_STATUS):
        evaluation = _evaluate(_inputs(report_type=report_type))
        assert evaluation.decision is ReleaseDecision.RESTRICT
        assert evaluation.release_status is ReportReleaseStatus.RESTRICTED


def test_governance_claim_triggers_review() -> None:
    evaluation = _evaluate(_inputs(claims=(_claim(ClaimType.CAUSAL, ClaimImportance.HIGH),)))
    assert evaluation.decision is ReleaseDecision.REQUIRE_REVIEW
    assert evaluation.release_status is ReportReleaseStatus.REVIEW_REQUIRED
    assert evaluation.review_status is ReportReviewStatus.PENDING
    assert "GOVERNANCE_CLAIM_SCOPE" in evaluation.basis["governance_triggers"]


def test_governance_finding_triggers_review() -> None:
    evaluation = _evaluate(_inputs(findings=(_finding(FindingSeverity.GOVERNANCE),)))
    assert evaluation.decision is ReleaseDecision.REQUIRE_REVIEW
    assert "GOVERNANCE_FINDING" in evaluation.basis["governance_triggers"]


def test_probable_or_disputed_in_key_sections_triggers_review() -> None:
    evaluation = _evaluate(_inputs(probable_or_disputed_in_key_sections=True))
    assert evaluation.decision is ReleaseDecision.REQUIRE_REVIEW


def test_unresolved_conflicts_trigger_review() -> None:
    evaluation = _evaluate(_inputs(unresolved_nonblocking_conflicts=("conflict:x",)))
    assert evaluation.decision is ReleaseDecision.REQUIRE_REVIEW


def test_governance_never_fires_when_hard_findings_exist() -> None:
    evaluation = _evaluate(
        _inputs(
            findings=(_finding(FindingSeverity.HARD), _finding(FindingSeverity.GOVERNANCE)),
            claims=(_claim(ClaimType.ATTRIBUTION, ClaimImportance.CRITICAL),),
            probable_or_disputed_in_key_sections=True,
            governance_profile_requires_review=True,
        )
    )
    assert evaluation.decision is ReleaseDecision.BLOCK
    assert evaluation.basis["governance_triggers"] == []


def test_evaluation_hash_is_stable_and_content_addressed() -> None:
    first = _evaluate(_inputs())
    again = ReportReleasePolicy().evaluate(_inputs(), evaluation_id="EVA-different", created_at=NOW)
    assert first.evaluation_hash == again.evaluation_hash
    changed = _evaluate(_inputs(findings=(_finding(FindingSeverity.GOVERNANCE),)))
    assert changed.evaluation_hash != first.evaluation_hash
    assert changed.basis["approval_target"]["release_status"] == "PUBLISHED"
    assert changed.basis["rejection_target"]["release_status"] == "DRAFT"


def test_restricted_ceiling_inside_approval_target() -> None:
    evaluation = _evaluate(
        _inputs(
            report_type=ReportType.RESTRICTED_INVESTIGATION,
            findings=(_finding(FindingSeverity.GOVERNANCE),),
        )
    )
    assert evaluation.basis["approval_target"]["release_status"] == "RESTRICTED"
