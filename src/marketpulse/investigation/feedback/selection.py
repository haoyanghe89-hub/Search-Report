from __future__ import annotations

import hashlib
from dataclasses import dataclass

from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.agents.contracts import ArtifactView
from marketpulse.investigation.domain.enums import ArtifactType
from marketpulse.investigation.domain.locators import (
    EvidenceLocator,
    PdfTextRangeLocator,
    TextRangeLocator,
)
from marketpulse.investigation.domain.sources import DocumentArtifact, Source, SourceSnapshot


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    artifact: DocumentArtifact
    snapshot: SourceSnapshot
    source: Source
    from_current_task: bool = False
    relevant_to_question: bool = False
    related_to_gap: bool = False
    related_to_conflict: bool = False


class ArtifactSelector:
    def __init__(
        self,
        blobs: BlobStoragePort,
        *,
        max_artifacts: int,
        max_excerpts: int,
        max_chars: int,
    ) -> None:
        self._blobs = blobs
        self._max_artifacts = max_artifacts
        self._max_excerpts = max_excerpts
        self._max_chars = max_chars

    def select(self, candidates: tuple[ArtifactCandidate, ...]) -> tuple[ArtifactView, ...]:
        ordered = sorted(candidates, key=self._sort_key)
        output: list[ArtifactView] = []
        remaining = self._max_chars
        limit = min(len(ordered), self._max_artifacts, self._max_excerpts)
        per_excerpt = max(1, self._max_chars // max(1, limit))
        for candidate in ordered[:limit]:
            if remaining <= 0:
                break
            content = self._blobs.get_bytes(candidate.artifact.blob_ref).decode(
                "utf-8", errors="replace"
            )
            excerpt = content[: min(remaining, per_excerpt)]
            if not excerpt:
                continue
            remaining -= len(excerpt)
            quote_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            locator: EvidenceLocator
            if candidate.artifact.artifact_type is ArtifactType.PDF_PAGE_TEXT:
                locator = PdfTextRangeLocator(
                    page=candidate.artifact.page_number or 1,
                    start=0,
                    end=len(excerpt),
                    quote_hash=quote_hash,
                )
            else:
                locator = TextRangeLocator(start=0, end=len(excerpt), quote_hash=quote_hash)
            output.append(
                ArtifactView(
                    artifact_key=f"ART-{candidate.artifact.sha256[:24]}",
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

    @staticmethod
    def _sort_key(candidate: ArtifactCandidate) -> tuple[int, str]:
        score = (
            16 * int(candidate.from_current_task)
            + 8 * int(candidate.relevant_to_question)
            + 4 * int(candidate.source.is_official or candidate.source.is_first_hand)
            + 2 * int(candidate.related_to_gap)
            + int(candidate.related_to_conflict)
        )
        return (-score, candidate.artifact.artifact_id)
