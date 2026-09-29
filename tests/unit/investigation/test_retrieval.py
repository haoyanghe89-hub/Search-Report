from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.evaluation.offline import Corpus, _candidates
from marketpulse.investigation.feedback.retrieval import BM25ArtifactSelector, segment_ranges
from marketpulse.investigation.feedback.selection import ArtifactSelector


def corpus(documents):
    return Corpus.model_validate(
        {
            "dataset_kind": "synthetic",
            "documents": documents,
            "cases": [{"id": "case", "question": "test", "labels": []}],
        }
    )


@pytest.mark.parametrize("quote", ["故障原因是传感器过热。", "The sensor overheated unexpectedly."])
def test_retrieves_tail_with_same_budget_and_exact_offsets(tmp_path: Path, quote: str):
    text = "Unrelated background.\n" * 240 + quote
    blobs = LocalContentAddressedBlobStorage(tmp_path)
    candidates = _candidates(corpus([{"id": "doc", "text": text}]), blobs)
    limits = dict(max_artifacts=1, max_excerpts=1, max_chars=160)
    old = ArtifactSelector(blobs, **limits).select(candidates)
    new = BM25ArtifactSelector(blobs, **limits).select(candidates, query=quote)
    assert quote not in old[0].excerpt
    assert quote in new[0].excerpt
    view = new[0]
    assert view.excerpt == text[view.locator.start : view.locator.end]
    assert view.locator.quote_hash == hashlib.sha256(view.excerpt.encode()).hexdigest()
    assert len(view.excerpt) <= 160
    assert "char-window-1200-overlap-160-v1" in view.artifact_key


def test_pdf_page_identity_duplicate_content_and_permutation(tmp_path: Path):
    blobs = LocalContentAddressedBlobStorage(tmp_path)
    candidates = _candidates(
        corpus(
            [
                {"id": "page-2", "text": "Same repeated evidence.", "page": 2},
                {"id": "page-7", "text": "Same repeated evidence.", "page": 7},
            ]
        ),
        blobs,
    )
    selector = BM25ArtifactSelector(blobs, max_artifacts=2, max_excerpts=2, max_chars=100)
    views = selector.select(candidates, query="evidence")
    assert views == selector.select(tuple(reversed(candidates)), query="evidence")
    assert len({v.artifact_key for v in views}) == 2
    assert {v.locator.page for v in views} == {2, 7}


def test_segments_cover_archive_and_respect_all_limits(tmp_path: Path):
    text = "A long paragraph.\n" * 300
    spans = segment_ranges(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(0 < end - start <= 1200 for start, end in spans)
    assert all(
        next_start < end for (_, end), (next_start, _) in zip(spans, spans[1:], strict=False)
    )
    blobs = LocalContentAddressedBlobStorage(tmp_path)
    candidates = _candidates(
        corpus([{"id": str(i), "text": str(i) + text} for i in range(4)]), blobs
    )
    views = BM25ArtifactSelector(
        blobs,
        max_artifacts=2,
        max_excerpts=3,
        max_chars=301,
    ).select(candidates, query="paragraph")
    assert len({v.source_key for v in views}) <= 2
    assert len(views) <= 3
    assert sum(len(v.excerpt) for v in views) <= 301


def test_empty_and_corrupt_archives(tmp_path: Path):
    blobs = LocalContentAddressedBlobStorage(tmp_path)
    selector = BM25ArtifactSelector(blobs, max_artifacts=1, max_excerpts=1, max_chars=100)
    assert selector.select((), query="test") == ()
    candidates = _candidates(corpus([{"id": "doc", "text": "text"}]), blobs)
    candidate = candidates[0]
    from dataclasses import replace

    broken = replace(candidate, artifact=candidate.artifact.model_copy(update={"sha256": "a" * 64}))
    with pytest.raises(ValueError, match="hash mismatch"):
        selector.select((broken,), query="text")
