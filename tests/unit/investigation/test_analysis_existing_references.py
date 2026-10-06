from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    AnalysisProposal,
    ArtifactView,
    ExistingClaimView,
)
from marketpulse.investigation.agents.model_agents import ModelAnalystAgent
from marketpulse.investigation.domain.locators import TextRangeLocator
from marketpulse.investigation.recording.errors import InvalidProviderResponseError


@pytest.mark.parametrize("wrapped", [False, True])
def test_existing_qualifier_groups_keep_persisted_claim_identity_and_status(wrapped):
    from datetime import UTC, datetime

    from marketpulse.investigation.agents.contracts import ClaimCandidate, validate_agent_proposal
    from marketpulse.investigation.agents.normalization import normalize_existing_claim_references
    from marketpulse.investigation.feedback.context import claim_key
    from marketpulse.investigation.feedback.guards import ClaimGuard

    now = datetime.now(UTC)
    guard = ClaimGuard()
    first = guard.materialize(
        ClaimCandidate(
            claim_key="original",
            statement="The researcher reported 42 points on Benchmark A.",
            claim_type="QUANTITATIVE",
            entity_qualifiers={"speaker": "Author"},
            time_qualifiers={"date": "2026-10-01"},
            scope_qualifiers={"benchmark": "A"},
            critical=True,
        ),
        investigation_id="I",
        run_id="R",
        existing_claims=(),
        created_by_step_id="step",
        research_task_id="task",
        now=now,
    ).claim
    existing = ExistingClaimView(
        claim_key=claim_key(first),
        statement=first.statement,
        claim_type=first.claim_type,
        qualifiers=first.qualifiers,
        status=first.validation_status,
    )
    request = AnalysisInput(artifacts=(), existing_claims=(existing,))
    raw = {
        "relations": [{"claim_key": existing.claim_key, "evidence_key": "E1", "stance": "CONTEXT"}],
        "evidence": [
            {
                "evidence_key": "E1",
                "artifact_key": "A1",
                "quote": "original text",
                "locator": {"locator_type": "TEXT_RANGE", "start": 0, "end": 13},
            }
        ],
    }
    if wrapped:
        raw["claims"] = [
            {
                "claim_key": existing.claim_key,
                "statement": existing.statement,
                "claim_type": existing.claim_type.value,
                "entity_qualifiers": existing.qualifiers,
            }
        ]
    proposal = AnalysisProposal.model_validate(normalize_existing_claim_references(raw, request))
    candidate = proposal.claims[0]
    result = guard.materialize(
        candidate,
        investigation_id="I",
        run_id="R",
        existing_claims=(first,),
        created_by_step_id="new-step",
        research_task_id="new-task",
        now=now,
    )
    assert result.reused and result.claim == first
    assert result.claim.is_critical
    # The canonical definition cannot be swapped while claiming to reuse its ID.
    candidate = candidate.model_copy(update={"canonical_statement": "An invented different fact."})
    with pytest.raises(ValueError, match="existing claim definition"):
        validate_agent_proposal(request, AnalysisProposal(claims=(candidate,)))


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["CLAIM-real", "CLAIM-fabricated"])
async def test_existing_reference_normalization_never_invents_claim_or_evidence(key):
    locator = TextRangeLocator(start=0, end=13, quote_hash="a" * 64)
    request = AnalysisInput(
        artifacts=(
            ArtifactView(
                artifact_key="ART-real",
                snapshot_key="SS-real",
                content_hash="a" * 64,
                excerpt="original fact",
                locator=locator,
            ),
        ),
        existing_claims=(
            ExistingClaimView(
                claim_key="CLAIM-real",
                statement="An existing attributed statement.",
                claim_type="STATEMENT",
                qualifiers={
                    "speaker": "Author",
                    "entity": {"speaker": "Author"},
                    "time": {},
                    "scope": {},
                },
                status="UNVERIFIED",
            ),
        ),
    )
    raw = {
        "evidence": [
            {
                "evidence_key": "E1",
                "artifact_key": "ART-real",
                "quote": "original fact",
                "locator": locator.model_dump(),
            }
        ],
        "relations": [{"claim_key": key, "evidence_key": "E1", "stance": "CONTEXT"}],
    }
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=json.dumps(raw)),
                )
            ]
        )
    )
    adapter = OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="test",
        default_model="test",
    )
    agent = ModelAnalystAgent(adapter, repair_attempts=0)
    if key == "CLAIM-fabricated":
        with pytest.raises(InvalidProviderResponseError):
            await agent.analyze(request, ground_quotes=True)
    else:
        result = await agent.analyze(request, ground_quotes=True)
        assert result.claims[0].statement == request.existing_claims[0].statement
        assert result.claims[0].entity_qualifiers == request.existing_claims[0].qualifiers["entity"]
        assert result.claims[0].claim_type == request.existing_claims[0].claim_type
        assert result.claims[0].supporting_evidence_keys == ()
        assert result.relations[0].stance.value == "CONTEXT"  # Not promoted to support.
        assert result.relations[0].claim_key == "CLAIM-real"
        assert create.await_count == 1
    # The stand-alone strict contract remains strict without trusted input normalization.
    with pytest.raises(ValueError):
        AnalysisProposal.model_validate(raw)
