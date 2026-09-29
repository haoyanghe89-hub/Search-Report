"""Opt-in provider check with synthetic text only; no saved investigation data."""

from __future__ import annotations

import os

import pytest
from openai import AsyncOpenAI

from marketpulse.config import Settings
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    ArtifactView,
    VerificationInput,
)
from marketpulse.investigation.agents.model_agents import ModelAnalystAgent
from marketpulse.investigation.feedback.verification_team import verification_team
from marketpulse.investigation.ingestion.locators import make_text_locator
from marketpulse.investigation.recording.errors import InvalidProviderResponseError


@pytest.mark.live
@pytest.mark.asyncio
async def test_synthetic_schema_repair_and_compact_verifier():
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 for synthetic model acceptance")
    settings = Settings.from_env()
    if not settings.deepseek_api_key:
        pytest.skip("model key required")
    excerpt = "This is a fictional test record. The sample library opened on Monday."
    locator = make_text_locator(excerpt, 0, len(excerpt))
    async with AsyncOpenAI(
        api_key=settings.deepseek_api_key.get_secret_value(), base_url=settings.deepseek_base_url
    ) as client:
        adapter = OpenAICompatibleModelAdapter(
            client, provider="test", default_model=settings.model, thinking_enabled=False
        )

        class FailFirst:
            calls = 0

            async def generate(self, request):
                self.calls += 1
                if self.calls == 1:
                    raise InvalidProviderResponseError(
                        "synthetic failure", validation_issues=("claims.0.claim_type: enum",)
                    )
                assert "claims.0.claim_type: enum" in request.messages[-1].content
                return await adapter.generate(request)

        model = FailFirst()
        analysis = await ModelAnalystAgent(model).analyze(
            AnalysisInput(
                artifacts=(
                    ArtifactView(
                        artifact_key="ART-synthetic",
                        snapshot_key="SNAP-synthetic",
                        content_hash=locator.quote_hash,
                        excerpt=excerpt,
                        locator=locator,
                    ),
                )
            ),
            ground_quotes=True,
        )
        assert model.calls == 2
        assert analysis.evidence and analysis.claims
        for evidence in analysis.evidence:
            assert excerpt[evidence.locator.start : evidence.locator.end] == evidence.quote
        verification = await verification_team(
            VerificationInput(claims=analysis.claims, evidence=analysis.evidence),
            lambda _: adapter,
            workers=4,
        )
        assert verification.judgments
        assert all(
            j.claim_key in {c.claim_key for c in analysis.claims} for j in verification.judgments
        )
