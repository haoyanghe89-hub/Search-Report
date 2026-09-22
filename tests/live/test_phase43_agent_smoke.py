from __future__ import annotations

import hashlib
import os

import pytest
from openai import AsyncOpenAI

from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    ArtifactView,
    ClaimCandidate,
    EvidenceCandidate,
    PlanInput,
    QuestionView,
    ResearchInput,
    TaskProposal,
    VerificationInput,
)
from marketpulse.investigation.agents.model_agents import (
    ModelAnalystAgent,
    ModelPlannerAgent,
    ModelResearcherAgent,
    ModelVerifierAgent,
)
from marketpulse.investigation.domain.enums import SourceType
from marketpulse.investigation.ingestion.locators import make_text_locator


@pytest.mark.live
@pytest.mark.asyncio
async def test_phase43_real_structured_agents_smoke() -> None:
    key = os.getenv("DEEPSEEK_API_KEY")
    if os.getenv("RUN_LIVE_TESTS") != "1" or not key:
        pytest.skip("set RUN_LIVE_TESTS=1 and DEEPSEEK_API_KEY to run")
    model = OpenAICompatibleModelAdapter(
        AsyncOpenAI(
            api_key=key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ),
        provider="deepseek",
        default_model=os.getenv("MARKETPULSE_MODEL", "deepseek-chat"),
    )
    planner = ModelPlannerAgent(model, max_output_tokens=1200)
    plan = await planner.plan(
        PlanInput(
            case_key="controlled-public-event",
            scope_summary="One controlled public document",
            investigation_goal="Determine what the supplied record states",
            event_description="A controlled schema smoke fixture",
            questions=(
                QuestionView(
                    question_key="Q-1",
                    text="What does the controlled record state?",
                    is_critical=True,
                ),
            ),
            critical_question_keys=("Q-1",),
            max_research_rounds=1,
        )
    )
    assert plan.tasks and plan.tasks[0].target_question_key == "Q-1"

    task = TaskProposal(
        task_key="controlled-task",
        target_question_key="Q-1",
        objective="Find the controlled record",
        purpose="Supply one exact source excerpt",
        priority=100,
    )
    research = await ModelResearcherAgent(model, max_output_tokens=1000).research(
        ResearchInput(task=task, remaining_search_calls=1)
    )
    assert len(research.queries) <= 1

    excerpt = "The controlled public record states that the event occurred."
    locator = make_text_locator(excerpt, 0, len(excerpt))
    analyst = await ModelAnalystAgent(model, max_output_tokens=1600).analyze(
        AnalysisInput(
            artifacts=(
                ArtifactView(
                    artifact_key="ART-controlled",
                    snapshot_key="SNAP-controlled",
                    content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                    excerpt=excerpt,
                    locator=locator,
                    source_key="SOURCE-controlled",
                    source_title="Controlled public record",
                    source_type=SourceType.OFFICIAL_REPORT,
                    is_official=True,
                    is_first_hand=True,
                ),
            ),
            target_question=QuestionView(
                question_key="Q-1",
                text="What does the controlled record state?",
                is_critical=True,
            ),
        )
    )
    assert all(item.artifact_key == "ART-controlled" for item in analyst.evidence)

    claims = analyst.claims or (
        ClaimCandidate(
            claim_key="C-controlled",
            statement=excerpt,
            claim_type="STATEMENT",
        ),
    )
    evidence = analyst.evidence or (
        EvidenceCandidate(
            evidence_key="E-controlled",
            artifact_key="ART-controlled",
            quote=excerpt,
            locator=locator,
            quote_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        ),
    )
    verification = await ModelVerifierAgent(model, max_output_tokens=1200).verify(
        VerificationInput(claims=claims, evidence=evidence)
    )
    assert verification.contract_version == "2"
