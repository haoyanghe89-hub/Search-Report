from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from marketpulse.investigation.agents.contracts import VerificationProposal
from marketpulse.investigation.case_replay import _FixtureModel
from marketpulse.investigation.ports.external import ModelMessage, ModelRequest

CASE_ROOT = Path(__file__).resolve().parents[3] / "case_data" / "east_palestine_2023"


def test_curated_verifier_rejects_swapped_and_unknown_evidence() -> None:
    model = _FixtureModel(CASE_ROOT)
    cause = next(pair for pair in model.pairs if pair["key"] == "cause")
    monitoring = next(pair for pair in model.pairs if pair["key"] == "epa-air-scope")
    context = {
        "claims": [
            {
                "claim_key": "cause",
                "statement": cause["statement"],
                "supporting_evidence_keys": ["right", "swapped", "unknown"],
            }
        ],
        "evidence": [
            {"evidence_key": "right", "quote": cause["quote"]},
            {"evidence_key": "swapped", "quote": monitoring["quote"]},
            {"evidence_key": "unknown", "quote": "Invented and unreviewed material."},
        ],
    }
    result = asyncio.run(
        model.generate(
            ModelRequest(
                messages=(
                    ModelMessage(role="system", content="Offline regression"),
                    ModelMessage(role="user", content=json.dumps({"bounded_context": context})),
                ),
                response_model=VerificationProposal,
                response_schema_version="1",
                prompt_version="test",
            )
        )
    )
    judgments = {item.evidence_key: item.entailment.value for item in result.output.judgments}
    assert judgments == {"right": "ENTAILS", "swapped": "NOT_RELEVANT", "unknown": "NOT_RELEVANT"}
    assert "not-live-llm" in result.provider
    assert result.usage.input_tokens == result.usage.output_tokens == 0


def test_analysis_binds_only_exact_source_specific_quote_and_preserves_offsets() -> None:
    model = _FixtureModel(CASE_ROOT)
    pair = next(pair for pair in model.pairs if pair["key"] == "cause")
    text = "navigation prefix\n" + pair["quote"] + "\nunrelated footer"
    artifacts = [
        {
            "artifact_key": "correct",
            "source_title": model.source_titles[pair["source_filename"]],
            "excerpt": text,
            "locator": {"type": "TEXT_RANGE", "start": 80, "end": 80 + len(text)},
        },
        {
            "artifact_key": "wrong-publisher",
            "source_title": "EPA regional statement on the East Palestine derailment",
            "excerpt": text,
            "locator": {"type": "TEXT_RANGE", "start": 0, "end": len(text)},
        },
    ]
    proposal = model._analysis_payload({"artifacts": artifacts})
    claim = next(item for item in proposal["claims"] if item["claim_key"] == "cause")
    assert claim["supporting_evidence_keys"] == ["evidence-cause"]
    evidence = next(
        item for item in proposal["evidence"] if item["evidence_key"] == "evidence-cause"
    )
    assert evidence["artifact_key"] == "correct"
    assert evidence["quote"] == pair["quote"]
    assert evidence["locator"]["start"] == 80 + len("navigation prefix\n")
    assert evidence["locator"]["end"] - evidence["locator"]["start"] == len(pair["quote"])
    assert evidence["quote_hash"] == hashlib.sha256(pair["quote"].encode()).hexdigest()
    assert all(
        not item["supporting_evidence_keys"]
        for item in proposal["claims"]
        if item["claim_key"] != "cause"
    )
