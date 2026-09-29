from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    AnalysisProposal,
    ArtifactView,
    EvidenceCandidate,
)
from marketpulse.investigation.agents.model_agents import ModelAnalystAgent
from marketpulse.investigation.domain.locators import PdfTextRangeLocator, TextRangeLocator
from marketpulse.investigation.ports.external import ModelMessage, ModelRequest
from marketpulse.investigation.recording.errors import ModelOutputTruncatedError


@pytest.mark.asyncio
async def test_schema_repair_receives_safe_field_errors():
    import json

    from marketpulse.investigation.agents.contracts import VerificationInput
    from marketpulse.investigation.agents.model_agents import ModelVerifierAgent

    responses = [
        {
            "judgments": [
                {
                    "claim_key": "C1",
                    "evidence_key": "E1",
                    "entailment": "INVALID_SECRET_VALUE",
                    "rationale": "test",
                }
            ],
            "SECRET_FIELD": "secret",
        },
        {},
    ]
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=json.dumps(responses.pop(0))),
                )
            ]
        )

    adapter = OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="test",
        default_model="test",
    )
    await ModelVerifierAgent(adapter).verify(VerificationInput(claims=(), evidence=()))
    repair = calls[1]["messages"][-2]["content"]
    assert "judgments.0.entailment: enum" in repair
    assert "extra_forbidden" in repair
    assert "SECRET" not in repair


@pytest.mark.asyncio
async def test_verifier_repair_identifies_wrong_reference_and_never_accepts_it():
    from marketpulse.investigation.agents.contracts import (
        SemanticJudgment,
        VerificationInput,
        VerificationProposal,
    )
    from marketpulse.investigation.agents.model_agents import ModelVerifierAgent
    from marketpulse.investigation.recording.errors import InvalidProviderResponseError

    invalid = VerificationProposal(
        judgments=(
            SemanticJudgment(
                claim_key="nonexistent",
                evidence_key="nonexistent",
                entailment="ENTAILS",
                rationale="test",
            ),
        )
    )
    generate = AsyncMock(return_value=SimpleNamespace(output=invalid))
    with pytest.raises(InvalidProviderResponseError):
        await ModelVerifierAgent(SimpleNamespace(generate=generate)).verify(
            VerificationInput(claims=(), evidence=())
        )
    assert "unknown claim or evidence" in generate.call_args_list[1].args[0].messages[-1].content


@pytest.mark.asyncio
async def test_compact_verifier_ids_restore_exact_original_reference():
    import json

    from marketpulse.investigation.agents.contracts import ClaimCandidate, VerificationInput
    from marketpulse.investigation.feedback.verification_team import verification_team
    from marketpulse.investigation.ports.external import StructuredModelResult

    original_claim = "CLAIM-1a0e3097d949a7a1c94e97f0"
    original_evidence = "EVID-aabbccddeeff001122334455"

    async def generate(request):
        context = json.loads(request.messages[1].content)["bounded_context"]
        assert context["claims"][0]["claim_key"] == "C1"
        assert context["evidence"][0]["evidence_key"] == "E1"
        return StructuredModelResult(
            output=request.response_model.model_validate(
                {
                    "judgments": [
                        {
                            "claim_key": "C1",
                            "evidence_key": "E1",
                            "entailment": "ENTAILS",
                            "rationale": "exact text",
                        }
                    ],
                    "gaps": [
                        {
                            "gap_key": "G1",
                            "gap_type": "EVIDENCE_GAP",
                            "target_claim_key": "C1",
                            "reason": "needs corroboration",
                        }
                    ],
                }
            ),
            provider="test",
            model="test",
        )

    result = await verification_team(
        VerificationInput(
            claims=(
                ClaimCandidate(
                    claim_key=original_claim,
                    statement="test",
                    claim_type="EVENT_FACT",
                    supporting_evidence_keys=(original_evidence,),
                ),
            ),
            evidence=(
                EvidenceCandidate(
                    evidence_key=original_evidence,
                    artifact_key="A",
                    quote="test",
                    locator=TextRangeLocator(start=0, end=4, quote_hash="a" * 64),
                ),
            ),
        ),
        lambda _: SimpleNamespace(generate=generate),
        workers=4,
    )
    assert result.judgments[0].claim_key == original_claim
    assert result.judgments[0].evidence_key == original_evidence
    assert result.gaps[0].target_claim_key == original_claim


@pytest.mark.asyncio
@pytest.mark.parametrize("model,extra", [("deepseek-flash", True), ("other-model", False)])
async def test_thinking_option_is_provider_specific_and_truncation_is_explicit(model, extra):
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length", message=SimpleNamespace(content='{"evidence":[')
                )
            ]
        )
    )
    adapter = OpenAICompatibleModelAdapter(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        provider="test",
        default_model=model,
        thinking_enabled=False,
    )
    with pytest.raises(ModelOutputTruncatedError):
        await adapter.generate(
            ModelRequest(
                messages=(ModelMessage(role="user", content="analyze"),),
                response_model=AnalysisProposal,
                response_schema_version="v1",
                prompt_version="v1",
            )
        )
    assert ("extra_body" in create.call_args.kwargs) is extra
    if extra:
        assert create.call_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("pdf", [False, True])
async def test_live_quote_binding_uses_exact_source_offset_hash_and_page(pdf):
    excerpt = "前缀。The update failed. End."
    quote = "The update failed."
    locator_cls = PdfTextRangeLocator if pdf else TextRangeLocator
    locator = locator_cls(
        start=100, end=100 + len(excerpt), quote_hash="a" * 64, **({"page": 3} if pdf else {})
    )
    candidate = EvidenceCandidate(evidence_key="E", artifact_key="A", quote=quote, locator=locator)
    model = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(output=AnalysisProposal(evidence=(candidate,)))
        )
    )
    result = await ModelAnalystAgent(model).analyze(
        AnalysisInput(
            artifacts=(
                ArtifactView(
                    artifact_key="A",
                    snapshot_key="S",
                    content_hash="b" * 64,
                    excerpt=excerpt,
                    locator=locator,
                ),
            )
        ),
        ground_quotes=True,
    )
    evidence = result.evidence[0]
    assert evidence.locator.start == 100 + excerpt.index(quote)
    assert evidence.locator.end == evidence.locator.start + len(quote)
    assert (
        evidence.quote_hash
        == evidence.locator.quote_hash
        == hashlib.sha256(quote.encode()).hexdigest()
    )
    if pdf:
        assert evidence.locator.page == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "excerpt,quote", [("original text", "invented text"), ("same same", "same")]
)
async def test_missing_or_ambiguous_quote_does_not_get_a_computed_locator(excerpt, quote):
    locator = TextRangeLocator(start=0, end=len(excerpt), quote_hash="a" * 64)
    candidate = EvidenceCandidate(evidence_key="E", artifact_key="A", quote=quote, locator=locator)
    model = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(output=AnalysisProposal(evidence=(candidate,)))
        )
    )
    result = await ModelAnalystAgent(model).analyze(
        AnalysisInput(
            artifacts=(
                ArtifactView(
                    artifact_key="A",
                    snapshot_key="S",
                    content_hash="b" * 64,
                    excerpt=excerpt,
                    locator=locator,
                ),
            )
        ),
        ground_quotes=True,
    )
    assert result.evidence[0] == candidate


@pytest.mark.asyncio
async def test_truncated_output_retries_once_with_larger_output_budget():
    generate = AsyncMock(
        side_effect=[
            ModelOutputTruncatedError("truncated"),
            SimpleNamespace(output=AnalysisProposal()),
        ]
    )
    result = await ModelAnalystAgent(SimpleNamespace(generate=generate)).analyze(
        AnalysisInput(artifacts=())
    )
    assert result == AnalysisProposal()
    assert [call.args[0].max_output_tokens for call in generate.call_args_list] == [4000, 8000]


@pytest.mark.asyncio
async def test_whitespace_binding_stores_original_text_instead_of_model_quote():
    excerpt = "Prefix: company\nCrowdStrike\ndistributed a faulty update."
    quote = "company CrowdStrike distributed a faulty update."
    locator = TextRangeLocator(start=0, end=len(excerpt), quote_hash="a" * 64)
    candidate = EvidenceCandidate(evidence_key="E", artifact_key="A", quote=quote, locator=locator)
    model = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(output=AnalysisProposal(evidence=(candidate,)))
        )
    )
    result = await ModelAnalystAgent(model).analyze(
        AnalysisInput(
            artifacts=(
                ArtifactView(
                    artifact_key="A",
                    snapshot_key="S",
                    content_hash="b" * 64,
                    excerpt=excerpt,
                    locator=locator,
                ),
            )
        ),
        ground_quotes=True,
    )
    evidence = result.evidence[0]
    assert evidence.quote == excerpt[8:]
    assert evidence.locator.start == 8
    assert evidence.locator.end == len(excerpt)
    assert evidence.quote_hash == hashlib.sha256(excerpt[8:].encode()).hexdigest()
