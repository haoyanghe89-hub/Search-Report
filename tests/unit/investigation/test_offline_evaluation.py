from __future__ import annotations

import pytest
from pydantic import ValidationError

from marketpulse.investigation.evaluation import Corpus, EvaluationConfig, compare


def data():
    quote = "故障原因是传感器过热。"
    text = "背景信息。\n" * 600 + quote
    return {
        "dataset_kind": "synthetic",
        "documents": [{"id": "doc", "text": text, "page": 4}],
        "cases": [
            {
                "id": "cause",
                "question": quote,
                "labels": [
                    {
                        "document_id": "doc",
                        "start": len(text) - len(quote),
                        "end": len(text),
                        "quote": quote,
                        "stance": "supports",
                    }
                ],
            }
        ],
    }


def test_controlled_comparison_reproducible_and_no_network():
    corpus = Corpus.model_validate(data())
    config = EvaluationConfig(max_artifacts=1, max_excerpts=1, max_chars=160)
    result = compare(corpus, config)
    assert result == compare(corpus, config)
    assert result["network_calls"] == result["model_calls"] == 0
    assert result["totals"]["truncation"]["micro_span_recall"] == 0
    assert result["totals"]["bm25"]["micro_span_recall"] == 1
    assert result["cases"][0]["bm25"]["selected_chars"] <= 160


@pytest.mark.parametrize("mutation", ["range", "quote", "document", "duplicate"])
def test_invalid_annotation_fails(mutation):
    raw = data()
    label = raw["cases"][0]["labels"][0]
    if mutation == "range":
        label["end"] += 1
    elif mutation == "quote":
        label["quote"] = "invented"
    elif mutation == "document":
        label["document_id"] = "unknown"
    else:
        raw["cases"][0]["labels"].append(label.copy())
    with pytest.raises(ValidationError):
        Corpus.model_validate(raw)


def test_insufficient_evidence_is_not_scored_as_perfect_recall():
    raw = data()
    raw["cases"][0]["labels"] = []
    result = compare(Corpus.model_validate(raw))
    assert result["cases"][0]["bm25"]["span_recall"] is None
