from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import AnalysisInput, AnalysisProposal, ArtifactView
from marketpulse.investigation.agents.model_agents import ModelAnalystAgent
from marketpulse.investigation.domain.locators import TextRangeLocator
from marketpulse.investigation.recording.errors import InvalidProviderResponseError


def adapter_for(payload):
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=json.dumps(payload))
                )
            ]
        )
    )
    return OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="test",
        default_model="test",
    ), create


def payload(quote="original fact"):
    return {
        "evidence": [
            {
                "evidence_key": "E1",
                "artifact_key": "A1",
                "quote": quote,
                "locator": {"locator_type": "TEXT_RANGE", "start": 0, "end": 13},
            }
        ]
    }


def context():
    return AnalysisInput(
        artifacts=(
            ArtifactView(
                artifact_key="A1",
                snapshot_key="SS1",
                source_key="S-real",
                source_title="Original title",
                content_hash="a" * 64,
                excerpt="original fact",
                locator=TextRangeLocator(start=10, end=23, quote_hash="b" * 64),
            ),
        )
    )


@pytest.mark.asyncio
async def test_missing_nested_hash_normalizes_then_binds_to_exact_source():
    adapter, create = adapter_for(payload())
    result = await ModelAnalystAgent(adapter).analyze(context(), ground_quotes=True)
    evidence = result.evidence[0]
    assert evidence.locator.start == 10
    assert evidence.locator.quote_hash == hashlib.sha256(b"original fact").hexdigest()
    assert create.await_count == 1
    assert "locator.quote_hash" in create.call_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_missing_hash_does_not_make_invented_quote_valid():
    adapter, _ = adapter_for(payload("invented fact"))
    agent = ModelAnalystAgent(adapter)
    await agent.analyze(context(), ground_quotes=True)
    assert agent.grounding_diagnostics["E1"] == "QUOTE_NOT_FOUND"


@pytest.mark.asyncio
async def test_unknown_artifact_still_rejected_with_bounded_repairs():
    raw = payload()
    raw["evidence"][0]["artifact_key"] = "S-real"  # Source ID is NOT a locator ID.
    adapter, create = adapter_for(raw)
    with pytest.raises(InvalidProviderResponseError, match="reference validation"):
        await ModelAnalystAgent(adapter, sleep=AsyncMock()).analyze(context(), ground_quotes=True)
    assert create.await_count == 3


@pytest.mark.asyncio
async def test_local_reference_failure_has_actionable_safe_code_not_generic_value_error():
    raw = payload()
    raw["claims"] = [
        {
            "claim_key": "C1",
            "statement": "original fact",
            "claim_type": "STATEMENT",
            "supporting_evidence_keys": ["invented-secret-reference"],
        }
    ]
    adapter, _ = adapter_for(raw)
    with pytest.raises(InvalidProviderResponseError) as caught:
        await ModelAnalystAgent(adapter, repair_attempts=0).analyze(context(), ground_quotes=True)
    assert any("analysis_unknown_evidence" in issue for issue in caught.value.validation_issues)
    assert "secret" not in str(caught.value.validation_issues)


def test_supplied_hash_is_not_overwritten_or_invalid_references_deduplicated():
    raw = payload()
    raw["evidence"][0]["locator"]["quote_hash"] = "c" * 64
    parsed = AnalysisProposal.model_validate(raw)
    assert parsed.evidence[0].locator.quote_hash == "c" * 64
    raw["evidence"].append(raw["evidence"][0])
    with pytest.raises(ValueError):
        AnalysisProposal.model_validate(raw)
