import hashlib

import pytest

from marketpulse.investigation.agents.contracts import (
    VerificationInput,
    VerificationProposal,
    validate_agent_proposal,
)
from marketpulse.investigation.agents.supplements import supplemented_qualifiers


def context():
    quote = "Gemini score 77.9%, pass@1. Results as of October 2026."
    return VerificationInput.model_validate(
        {
            "claims": [
                {
                    "claim_key": "C1",
                    "statement": "Gemini score 77.9%",
                    "claim_type": "QUANTITATIVE",
                    "atomicity": {"is_atomic": True},
                    "supporting_evidence_keys": ["E1"],
                }
            ],
            "evidence": [
                {
                    "evidence_key": "E1",
                    "artifact_key": "A1",
                    "quote": quote,
                    "locator": {
                        "locator_type": "TEXT_RANGE",
                        "start": 0,
                        "end": len(quote),
                        "quote_hash": hashlib.sha256(quote.encode()).hexdigest(),
                    },
                }
            ],
        }
    )


def proposal(**updates):
    supplement = {
        "claim_key": "C1",
        "evidence_key": "E1",
        "field": "time",
        "value": "October 2026",
        "source_quote": "Results as of October 2026.",
        "time_reference": "RESULTS_AS_OF",
        **updates,
    }
    return VerificationProposal.model_validate(
        {
            "qualifier_supplements": [supplement],
            "judgments": [
                {
                    "claim_key": "C1",
                    "evidence_key": "E1",
                    "entailment": "ENTAILS",
                    "rationale": "Whole qualified claim supported by the quote.",
                }
            ],
        }
    )


def test_explicit_cited_time_preserves_groups():
    p = proposal()
    validate_agent_proposal(context(), p)
    result = supplemented_qualifiers(
        {"entity": {"value": 77.9}, "scope": {"scope": "DeepSWE"}}, p.qualifier_supplements
    )
    assert result["time"] == {"time": "October 2026", "time_reference": "RESULTS_AS_OF"}
    assert result["entity"] == {"value": 77.9}
    assert result["scope"] == {"scope": "DeepSWE"}


@pytest.mark.parametrize(
    "updates",
    [
        {"value": "September 2026"},
        {"evidence_key": "fake"},
        {"source_quote": "Published October 2026"},
        {"time_reference": None},
    ],
)
def test_guessed_or_uncited_time_rejected(updates):
    with pytest.raises(ValueError):
        validate_agent_proposal(context(), proposal(**updates))


def test_partial_is_not_enough_for_supplementation():
    p = proposal()
    p = p.model_copy(
        update={
            "judgments": (p.judgments[0].model_copy(update={"entailment": "PARTIALLY_SUPPORTS"}),)
        }
    )
    with pytest.raises(ValueError, match="ENTAILS"):
        validate_agent_proposal(context(), p)


@pytest.mark.parametrize(
    "field,value,group",
    [
        ("value", "77.9", "entity"),
        ("unit", "%", "entity"),
        ("scope", "Gemini", "scope"),
        ("definition", "pass@1", "scope"),
    ],
)
def test_explicit_numeric_core_supplements_preserve_groups(field, value, group):
    p = proposal(
        field=field, value=value, source_quote=context().evidence[0].quote, time_reference=None
    )
    validate_agent_proposal(context(), p)
    result = supplemented_qualifiers({"time": {"time": "October 2026"}}, p.qualifier_supplements)
    assert result[group][field] == value
    assert result["time"] == {"time": "October 2026"}
    occupied = context().claims[0].model_copy(update={f"{group}_qualifiers": {field: "other"}})
    with pytest.raises(ValueError, match="overwrite"):
        validate_agent_proposal(context().model_copy(update={"claims": (occupied,)}), p)
