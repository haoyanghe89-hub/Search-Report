from datetime import UTC, datetime

from marketpulse.investigation.domain.runtime import RunBudget


def budget(**changes):
    return RunBudget(
        run_id="run",
        max_research_rounds=3,
        max_search_calls=10,
        max_fetch_calls=10,
        max_model_calls=100,
        max_tokens=100000,
        max_wall_time_ms=100000,
        updated_at=datetime.now(UTC),
        **changes,
    )


def test_stage_floors_and_inflight_cost():
    from marketpulse.investigation.harness.stage_budget import StageBudgetPolicy

    policy = StageBudgetPolicy()
    assert policy.admits(budget(tokens_used=70000), "analyst.analyze", 2000)
    assert not policy.admits(budget(tokens_used=72000), "analyst.analyze", 2000)
    assert policy.admits(budget(tokens_used=72000), "verifier.verify", 2000)
    assert not policy.admits(budget(tokens_used=97000), "verifier.verify", 2000)
    assert not policy.admits(budget(tokens_used=68000), "researcher.research", 2000, inflight=5000)
    assert not policy.admits(budget(model_calls_used=84), "researcher.research", 1)
    assert policy.admits(budget(model_calls_used=84), "verifier.verify", 1)


def test_metadata_compaction_is_live_only_and_keeps_offline_context():
    from types import SimpleNamespace

    from marketpulse.investigation.domain.enums import GapStatus
    from marketpulse.investigation.feedback.context import AgentContextBuilder
    from marketpulse.investigation.feedback.models import FeedbackLoopConfig

    reason = "recorded diagnostic " * 60
    state = SimpleNamespace(
        snapshots=(),
        sources=(),
        gaps=(SimpleNamespace(source_id="S", reason=reason, status=GapStatus.OPEN),) * 2,
    )
    offline = AgentContextBuilder(None, None, FeedbackLoopConfig())
    live = AgentContextBuilder(None, None, FeedbackLoopConfig(metadata_chars=500))
    assert offline.coverage(state).failed_or_unreadable_sources == (reason, reason)
    assert live.coverage(state).failed_or_unreadable_sources == (reason[:500],)


def test_live_context_limits_are_configured_not_total_budget_increase():
    from marketpulse.config import Settings
    from marketpulse.investigation.recovery import live_feedback_config

    settings = Settings()
    config = live_feedback_config(settings)
    assert settings.max_tokens == 2000000
    assert config.max_artifacts == 8
    assert config.max_excerpts == 16
    assert config.max_context_chars == 24000
    assert config.max_context_items == 16
    assert config.model_budget_reservations


def test_exact_semantic_reuse_invalidates_changed_statement_and_quote():
    from marketpulse.investigation.agents.contracts import (
        ClaimCandidate,
        EvidenceCandidate,
        SemanticJudgment,
        VerificationInput,
        VerificationProposal,
    )
    from marketpulse.investigation.domain.locators import TextRangeLocator
    from marketpulse.investigation.feedback.semantic_reuse import reusable_judgments

    evidence = EvidenceCandidate(
        evidence_key="E",
        artifact_key="A",
        quote="A happened.",
        locator=TextRangeLocator(start=0, end=11, quote_hash="a" * 64),
    )
    claim = ClaimCandidate(
        claim_key="C",
        statement="A happened.",
        claim_type="EVENT_FACT",
        supporting_evidence_keys=("E",),
    )
    request = VerificationInput(claims=(claim,), evidence=(evidence,))
    proposal = VerificationProposal(
        judgments=(
            SemanticJudgment(
                claim_key="C",
                evidence_key="E",
                entailment="ENTAILS",
                rationale="Verbatim support",
            ),
        )
    )
    assert reusable_judgments(request, ((request, proposal),)) == proposal.judgments
    changed = request.model_copy(
        update={"claims": (claim.model_copy(update={"statement": "A did not happen."}),)}
    )
    assert not reusable_judgments(changed, ((request, proposal),))
    changed = request.model_copy(
        update={"evidence": (evidence.model_copy(update={"quote": "B happened."}),)}
    )
    assert not reusable_judgments(changed, ((request, proposal),))
