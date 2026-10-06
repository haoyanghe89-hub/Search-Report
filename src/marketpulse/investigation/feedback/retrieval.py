"""Versioned, deterministic retrieval over immutable text (no index tables)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from marketpulse.investigation.agents.contracts import ArtifactView
from marketpulse.investigation.domain.enums import ArtifactType
from marketpulse.investigation.domain.locators import (
    EvidenceLocator,
    PdfTextRangeLocator,
    TextRangeLocator,
)
from marketpulse.investigation.feedback.selection import ArtifactCandidate, ArtifactSelector

RETRIEVAL_VERSION = "bm25-passages-v1"
SEGMENT_VERSION = "char-window-1200-overlap-160-v2"


def tokenize(text: str) -> tuple[str, ...]:
    """Latin words plus CJK unigrams/bigrams; independent of external dictionaries."""
    output = re.findall(r"[a-z0-9]+", text.casefold())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        output.extend(run)
        output.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tuple(output)


def segment_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Offsets always refer to the unchanged archive, including whitespace."""
    spans = []
    start = 0
    while start < len(text):
        end = min(start + 1200, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r"\n|[.!?。！？](?:\s|$)", text[start + 600 : end]))
            if boundaries:
                end = start + 600 + boundaries[-1].end()
        spans.append((start, end))
        if end == len(text):
            break
        start = end - 160
        # Overlap must not cut a word/benchmark label, e.g. DeepSWE -> eepSWE.
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        if start <= spans[-1][0]:
            start = end
    return tuple(spans)


@dataclass(frozen=True)
class Passage:
    document: int
    start: int
    end: int
    text: str


class BM25ArtifactSelector(ArtifactSelector):
    def select(
        self, candidates: tuple[ArtifactCandidate, ...], *, query: str = ""
    ) -> tuple[ArtifactView, ...]:
        ordered = sorted(
            candidates,
            key=lambda c: (
                self._sort_key(c),
                c.artifact.page_number or 0,
            ),
        )
        passages: list[Passage] = []
        seen_content: set[tuple[str, int | None]] = set()
        for index, candidate in enumerate(ordered):
            raw = self._blobs.get_bytes(candidate.artifact.blob_ref)
            if hashlib.sha256(raw).hexdigest() != candidate.artifact.sha256:
                raise ValueError("archived artifact hash mismatch")
            content_key = (candidate.artifact.sha256, candidate.artifact.page_number)
            if self._deduplicate and content_key in seen_content:
                continue
            seen_content.add(content_key)
            content = raw.decode("utf-8")
            passages.extend(
                Passage(index, start, end, content[start:end])
                for start, end in segment_ranges(content)
                if content[start:end].strip()
            )
        if not passages:
            return ()
        counts = [Counter(tokenize(p.text)) for p in passages]
        lengths = [sum(c.values()) for c in counts]
        average = max(1.0, sum(lengths) / len(lengths))
        df: Counter[str] = Counter()
        for count in counts:
            df.update(count.keys())
        query_terms = sorted(set(tokenize(query)))
        scores = []
        for count, length in zip(counts, lengths, strict=True):
            score = 0.0
            for term in query_terms:
                frequency = count[term]
                if frequency:
                    idf = math.log(1 + (len(passages) - df[term] + 0.5) / (df[term] + 0.5))
                    score += (
                        idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average))
                    )
            scores.append(score)
        ranked = sorted(
            range(len(passages)),
            key=lambda i: (-scores[i], passages[i].document, passages[i].start),
        )
        if self._deduplicate and any(score > 0 for score in scores):
            ranked = [i for i in ranked if scores[i] > 0]
        documents: list[int] = []
        first: list[int] = []
        for i in ranked:
            doc = passages[i].document
            if doc not in documents and len(documents) < self._max_artifacts:
                documents.append(doc)
                first.append(i)
        # Give each selected document one passage before filling spare excerpt slots.
        selected = first + [
            i for i in ranked if passages[i].document in documents and i not in first
        ]
        limit = min(self._max_excerpts, len(selected))
        per_excerpt = max(1, self._max_chars // max(1, limit))
        remaining = self._max_chars
        output = []
        for i in selected[:limit]:
            if remaining <= 0:
                break
            passage = passages[i]
            candidate = ordered[passage.document]
            width = min(per_excerpt, remaining)
            offset = 0
            if len(passage.text) > width and query_terms:
                # A small context budget must not reduce retrieval back to prefix-only.
                # Evaluate deterministic overlapping subwindows using the same vocabulary.
                offsets = sorted(
                    {
                        *range(0, len(passage.text) - width + 1, max(1, width // 2)),
                        len(passage.text) - width,
                    }
                )
                offset = max(
                    offsets,
                    key=lambda start: sum(
                        math.log(1 + (len(passages) - df[t] + 0.5) / (df[t] + 0.5))
                        for t in sorted(set(tokenize(passage.text[start : start + width])))
                        if t in query_terms
                    ),
                )
            # A ranked subwindow must not start halfway through an ASCII label either.
            while (
                0 < offset < len(passage.text)
                and passage.text[offset - 1].isascii()
                and passage.text[offset - 1].isalnum()
                and passage.text[offset].isascii()
                and passage.text[offset].isalnum()
            ):
                offset += 1
            start = passage.start + offset
            excerpt = passage.text[offset : offset + width]
            end = start + len(excerpt)
            remaining -= len(excerpt)
            digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            locator: EvidenceLocator
            if candidate.artifact.artifact_type is ArtifactType.PDF_PAGE_TEXT:
                locator = PdfTextRangeLocator(
                    page=candidate.artifact.page_number or 1,
                    start=start,
                    end=end,
                    quote_hash=digest,
                )
            else:
                locator = TextRangeLocator(start=start, end=end, quote_hash=digest)
            identity = hashlib.sha256(
                (
                    candidate.artifact.sha256
                    + candidate.snapshot.raw_sha256
                    + str(candidate.source.canonical_url)
                    + str(candidate.artifact.page_number)
                ).encode()
            ).hexdigest()[:24]
            output.append(
                ArtifactView(
                    artifact_key=f"ART-{identity}:{RETRIEVAL_VERSION}:{SEGMENT_VERSION}"
                    f":{start}:{end}",
                    snapshot_key=f"SNAP-{candidate.snapshot.raw_sha256[:24]}",
                    content_hash=candidate.artifact.sha256,
                    excerpt=excerpt,
                    locator=locator,
                    source_key=candidate.source.source_id,
                    source_title=candidate.source.title,
                    source_type=candidate.source.source_type,
                    is_official=candidate.source.is_official,
                    is_first_hand=candidate.source.is_first_hand,
                )
            )
        return tuple(output)
