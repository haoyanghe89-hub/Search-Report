from __future__ import annotations

import pytest
from pydantic import ValidationError

from marketpulse.investigation.agents.contracts import (
    GapProposal,
    PlanInput,
    PlanProposal,
    QueryIntent,
    QuestionView,
    ResearchInput,
    ResearchProposal,
    TaskProposal,
    VerificationProposal,
    WriterInput,
    WriterProposal,
    route_for_verification,
    validate_agent_proposal,
)
from marketpulse.investigation.domain.enums import ResearchGapType
from marketpulse.investigation.harness.state_machine import Route


def test_plan_must_cover_critical_question() -> None:
    request = PlanInput(
        case_key="case",
        scope_summary="public",
        questions=(QuestionView(question_key="Q1", text="Critical?", is_critical=True),),
        max_research_rounds=2,
    )
    with pytest.raises(ValueError, match="critical"):
        validate_agent_proposal(request, PlanProposal(tasks=()))
    proposal = PlanProposal(
        tasks=(
            TaskProposal(task_key="T1", target_question_key="Q1", objective="Search", priority=50),
        )
    )
    validate_agent_proposal(request, proposal)


def test_research_queries_cannot_exceed_budget_or_change_question() -> None:
    task = TaskProposal(
        task_key="T1", target_question_key="Q1", objective="Find records", priority=50
    )
    request = ResearchInput(task=task, remaining_search_calls=1)
    query = QueryIntent(
        query_key="q1",
        query="official report",
        target_question_key="Q1",
        purpose="primary source",
    )
    with pytest.raises(ValueError, match="budget"):
        validate_agent_proposal(request, ResearchProposal(queries=(query, query)))
    with pytest.raises(ValueError, match="another question"):
        validate_agent_proposal(
            request,
            ResearchProposal(queries=(query.model_copy(update={"target_question_key": "Q2"}),)),
        )


def test_verifier_routes_gaps_without_deciding_status() -> None:
    collect = VerificationProposal(
        gaps=(
            GapProposal(
                gap_key="G1",
                gap_type=ResearchGapType.SOURCE_CONFLICT,
                reason="conflicting sources",
            ),
        )
    )
    analyze = VerificationProposal(
        gaps=(
            GapProposal(
                gap_key="G2",
                gap_type=ResearchGapType.ANALYSIS_ERROR,
                reason="incorrect extraction",
            ),
        )
    )
    assert route_for_verification(collect) is Route.COLLECT
    assert route_for_verification(analyze) is Route.ANALYZE
    assert route_for_verification(VerificationProposal()) is Route.READY_FOR_REPORT
    with pytest.raises(ValidationError):
        VerificationProposal.model_validate({"status": "VERIFIED"})


def test_writer_contract_has_no_release_or_review_mutation() -> None:
    request = WriterInput(claims=())
    validate_agent_proposal(request, WriterProposal(sections=()))
    with pytest.raises(ValidationError):
        WriterProposal.model_validate({"sections": [], "review_status": "APPROVED"})
    with pytest.raises(ValidationError):
        WriterProposal.model_validate({"sections": [], "release_status": "PUBLISHED"})
