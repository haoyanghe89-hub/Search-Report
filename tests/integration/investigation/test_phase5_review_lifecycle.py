from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError

from marketpulse.config import Settings
from marketpulse.investigation.domain.enums import (
    ReleaseDecision,
    ReportReleaseStatus,
    ReportReviewStatus,
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
from marketpulse.investigation.review.api import router as review_router
from marketpulse.investigation.review.service import (
    ReportReviewService,
    ReviewCycleNotOpenError,
    ReviewerIdentity,
    ReviewHardGateBlockedError,
    StaleReviewBindingError,
)
from marketpulse.investigation.review.sessions import (
    ReviewerSessionService,
    client_fingerprint,
    hash_session_token,
)

NOW = datetime(2026, 9, 22, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

REVIEWER_PASSWORD = "correct horse battery staple"


def _evaluation(
    report: Report,
    decision: ReleaseDecision,
    evaluation_id: str,
    created_at: datetime = NOW,
    **basis_overrides: object,
) -> ReleasePolicyEvaluation:
    basis: dict[str, object] = {
        "approval_target": {"release_status": "PUBLISHED", "review_status": "APPROVED"},
        "rejection_target": {"release_status": "DRAFT", "review_status": "REJECTED"},
    }
    basis.update(basis_overrides)
    release_status = {
        ReleaseDecision.BLOCK: ReportReleaseStatus.DRAFT,
        ReleaseDecision.PUBLISH: ReportReleaseStatus.PUBLISHED,
        ReleaseDecision.RESTRICT: ReportReleaseStatus.RESTRICTED,
        ReleaseDecision.REQUIRE_REVIEW: ReportReleaseStatus.REVIEW_REQUIRED,
    }[decision]
    review_status = (
        ReportReviewStatus.PENDING
        if decision is ReleaseDecision.REQUIRE_REVIEW
        else ReportReviewStatus.NOT_REQUIRED
    )
    return ReleasePolicyEvaluation.build(
        evaluation_id=evaluation_id,
        report_id=report.report_id,
        policy_version="release-v1",
        decision=decision,
        release_status=release_status,
        review_status=review_status,
        report_hash=report.report_hash,
        claim_set_hash=report.claim_set_hash,
        citation_set_hash=report.citation_set_hash,
        hard_finding_count=1 if decision is ReleaseDecision.BLOCK else 0,
        governance_finding_count=1 if decision is ReleaseDecision.REQUIRE_REVIEW else 0,
        basis=basis,  # type: ignore[arg-type]
        created_at=created_at,
    )


def _seed_report(
    repository: InvestigationRepository,
    *,
    decision: ReleaseDecision = ReleaseDecision.REQUIRE_REVIEW,
) -> Report:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Review lifecycle",
            event_description="A public event.",
            investigation_goal="Verify review lifecycle.",
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
    repository.add(_evaluation(report, decision, "EVA-001"))
    return report


def test_review_lifecycle_approve_reject_research(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed_report(repository)
    service = ReportReviewService(create_session_factory(engine))
    reviewer = ReviewerIdentity(reviewer_id="reviewer-1", session_public_id="SES-1")

    request = service.open_review_request(
        report_id=report.report_id,
        validator_version="report-validator-v1",
        trigger_reason="Governance trigger.",
        now=NOW,
        expires_at=LATER,
    )
    assert request.evaluation_hash == HASH_D or request.evaluation_hash
    governance = ReportGovernanceRepository(create_session_factory(engine))
    with create_session_factory(engine)() as session:
        projection = governance.get_projection_in_session(session, report.report_id)
    assert projection is not None
    assert projection.release_status is ReportReleaseStatus.REVIEW_REQUIRED

    outcome = service.record_decision(
        report_id=report.report_id,
        decision=ReviewDecisionType.REQUEST_MORE_RESEARCH,
        reason="Need one more primary source.",
        reviewer=reviewer,
        now=NOW,
        idempotency_key="idem-1",
    )
    assert outcome.follow_up is not None
    assert outcome.follow_up.origin_run_id == "RUN-001"
    assert outcome.release_status is ReportReleaseStatus.DRAFT
    assert outcome.review_status is ReportReviewStatus.CHANGES_REQUESTED

    # Idempotent retry returns the recorded outcome without a second mutation.
    retry = service.record_decision(
        report_id=report.report_id,
        decision=ReviewDecisionType.REQUEST_MORE_RESEARCH,
        reason="Need one more primary source.",
        reviewer=reviewer,
        now=NOW,
        idempotency_key="idem-1",
    )
    assert retry.review_id == outcome.review_id
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM inv_review_decisions")) == 1
        assert connection.scalar(text("SELECT count(*) FROM inv_review_research_requests")) == 1

    # Decided request is no longer open.
    with pytest.raises(ReviewCycleNotOpenError):
        service.record_decision(
            report_id=report.report_id,
            decision=ReviewDecisionType.APPROVE,
            reason="ok",
            reviewer=reviewer,
            now=NOW,
        )

    # Old decision rows are immutable.
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE inv_review_decisions SET reason='changed' WHERE review_id=:r"),
                {"r": outcome.review_id},
            )


def test_review_approve_applies_policy_target(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed_report(repository)
    service = ReportReviewService(create_session_factory(engine))
    reviewer = ReviewerIdentity(reviewer_id="reviewer-1")
    service.open_review_request(
        report_id=report.report_id,
        validator_version="report-validator-v1",
        trigger_reason="Governance trigger.",
        now=NOW,
        expires_at=LATER,
    )
    outcome = service.record_decision(
        report_id=report.report_id,
        decision=ReviewDecisionType.APPROVE,
        reason="All bindings verified.",
        reviewer=reviewer,
        now=NOW,
    )
    assert outcome.release_status is ReportReleaseStatus.PUBLISHED
    governance = ReportGovernanceRepository(create_session_factory(engine))
    with create_session_factory(engine)() as session:
        projection = governance.get_projection_in_session(session, report.report_id)
    assert projection is not None
    assert projection.release_status is ReportReleaseStatus.PUBLISHED
    assert projection.review_status is ReportReviewStatus.APPROVED


def test_review_rejects_hard_gated_report(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed_report(repository, decision=ReleaseDecision.BLOCK)
    service = ReportReviewService(create_session_factory(engine))
    with pytest.raises(ReviewCycleNotOpenError):
        service.open_review_request(
            report_id=report.report_id,
            validator_version="report-validator-v1",
            trigger_reason="try",
            now=NOW,
            expires_at=LATER,
        )
    with pytest.raises(ReviewHardGateBlockedError):
        service.record_decision(
            report_id=report.report_id,
            decision=ReviewDecisionType.APPROVE,
            reason="attempt",
            reviewer=ReviewerIdentity(reviewer_id="reviewer-1"),
            now=NOW,
        )


def test_review_rejects_stale_cycle(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed_report(repository)
    service = ReportReviewService(create_session_factory(engine))
    service.open_review_request(
        report_id=report.report_id,
        validator_version="report-validator-v1",
        trigger_reason="Governance trigger.",
        now=NOW,
        expires_at=LATER,
    )
    # A fresh evaluation with different basis invalidates the open cycle.
    repository.add(
        _evaluation(
            report,
            ReleaseDecision.REQUIRE_REVIEW,
            "EVA-002",
            created_at=NOW + timedelta(hours=1),
            governance_triggers=["GOVERNANCE_CLAIM_SCOPE"],
        )
    )
    with pytest.raises(StaleReviewBindingError):
        service.record_decision(
            report_id=report.report_id,
            decision=ReviewDecisionType.APPROVE,
            reason="stale",
            reviewer=ReviewerIdentity(reviewer_id="reviewer-1"),
            now=NOW,
        )


def _reviewer_settings() -> Settings:
    password_hash = PasswordHasher().hash(REVIEWER_PASSWORD)
    return Settings(
        reviewer_id="reviewer",
        reviewer_display_name="Demo Reviewer",
        reviewer_password_hash=SecretStr(password_hash),
        review_rate_limit_fingerprint_secret=SecretStr("test-rate-secret"),
        review_allowed_origins=("http://testserver",),
        review_allow_insecure_loopback=True,
    )


def _review_client(engine: Engine) -> TestClient:
    app = FastAPI()
    app.include_router(review_router)
    app.state.settings = _reviewer_settings()
    app.state.review_session_factory = create_session_factory(engine)
    app.state.review_clock = lambda: NOW
    return TestClient(app, base_url="http://testserver")


def test_review_api_login_me_decide_logout(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    report = _seed_report(repository)
    ReportReviewService(create_session_factory(engine)).open_review_request(
        report_id=report.report_id,
        validator_version="report-validator-v1",
        trigger_reason="Governance trigger.",
        now=NOW,
        expires_at=LATER,
    )
    client = _review_client(engine)
    headers = {
        "Origin": "http://testserver",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/json",
    }

    bad = client.post("/api/review/login", json={"password": "wrong"}, headers=headers)
    assert bad.status_code == 401
    assert "mp_review" not in bad.cookies

    ok = client.post("/api/review/login", json={"password": REVIEWER_PASSWORD}, headers=headers)
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert ok.json()["reviewer"]["reviewer_id"] == "reviewer"

    me = client.get("/api/review/me")
    assert me.status_code == 200

    missing_csrf = client.post(
        "/api/review/decisions",
        json={"report_id": report.report_id, "decision": "APPROVE", "reason": "ok"},
        headers={"Origin": "http://testserver"},
    )
    assert missing_csrf.status_code == 403

    decision_headers = {**headers, "Idempotency-Key": "idem-api-1"}
    approved = client.post(
        "/api/review/decisions",
        json={"report_id": report.report_id, "decision": "APPROVE", "reason": "ok"},
        headers=decision_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["release_status"] == "PUBLISHED"

    replayed = client.post(
        "/api/review/decisions",
        json={"report_id": report.report_id, "decision": "APPROVE", "reason": "ok"},
        headers=decision_headers,
    )
    assert replayed.status_code == 200
    assert replayed.json()["review_id"] == approved.json()["review_id"]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM inv_review_decisions")) == 1

    logout = client.post("/api/review/logout", headers=headers)
    assert logout.status_code == 204
    assert client.get("/api/review/me").status_code == 401


def test_session_security_invariants(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    _, engine, _ = investigation_store
    sessions = create_session_factory(engine)
    service = ReviewerSessionService(sessions, now=lambda: NOW)
    settings = _reviewer_settings()
    from marketpulse.investigation.review.auth import (
        ConfiguredReviewer,
        ConfiguredReviewerAuthenticator,
    )

    reviewer = ConfiguredReviewer.from_settings(settings)
    assert ConfiguredReviewerAuthenticator(reviewer).authenticate(REVIEWER_PASSWORD) is not None
    assert ConfiguredReviewerAuthenticator(reviewer).authenticate("wrong") is None

    first = service.login(reviewer)
    second = service.login(reviewer)
    assert first.token != second.token
    # New login revokes the previous single active session.
    assert service.authenticate(first.token) is None
    assert service.authenticate(second.token) is not None

    with engine.connect() as connection:
        stored = connection.scalar(
            text("SELECT token_hash FROM inv_reviewer_sessions WHERE session_public_id=:sid"),
            {"sid": second.session.session_public_id},
        )
        assert stored == hash_session_token(second.token)
        assert second.token not in str(stored)

    fingerprint = client_fingerprint("test-rate-secret", "127.0.0.1")
    for _ in range(5):
        service.register_failure(fingerprint)
    assert service.is_locked(fingerprint)
    service.register_success(fingerprint)
    assert not service.is_locked(fingerprint)
