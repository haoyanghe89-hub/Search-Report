from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.agents.contracts import ArtifactView
from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus, SourceType
from marketpulse.investigation.domain.sources import DocumentArtifact, Source, SourceSnapshot
from marketpulse.investigation.feedback.retrieval import BM25ArtifactSelector
from marketpulse.investigation.feedback.selection import ArtifactCandidate, ArtifactSelector


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArchivedDocument(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    title: str = "Archived document"
    page: int | None = Field(default=None, ge=1)


class SpanLabel(StrictModel):
    document_id: str
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    stance: Literal["supports", "contradicts"]
    quote: str | None = None


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    labels: tuple[SpanLabel, ...]
    category: str = "unspecified"
    tags: tuple[str, ...] = ()


class Corpus(StrictModel):
    schema_version: Literal["archive-eval-v1"] = "archive-eval-v1"
    dataset_kind: Literal["synthetic", "annotated_real"]
    documents: tuple[ArchivedDocument, ...] = Field(min_length=1)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_annotations(self) -> Corpus:
        documents = {document.id: document for document in self.documents}
        if len(documents) != len(self.documents):
            raise ValueError("duplicate document id")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case id")
        for case in self.cases:
            seen: set[tuple[str, int, int, str]] = set()
            for label in case.labels:
                document = documents.get(label.document_id)
                if document is None:
                    raise ValueError(f"{case.id}: unknown document {label.document_id}")
                if not label.start < label.end <= len(document.text):
                    raise ValueError(f"{case.id}: label outside archived text")
                if (
                    label.quote is not None
                    and document.text[label.start : label.end] != label.quote
                ):
                    raise ValueError(f"{case.id}: quote differs from exact archived slice")
                key = (label.document_id, label.start, label.end, label.stance)
                if key in seen:
                    raise ValueError(f"{case.id}: duplicate label")
                seen.add(key)
        return self


class EvaluationConfig(StrictModel):
    max_artifacts: int = Field(default=12, ge=1)
    max_excerpts: int = Field(default=24, ge=1)
    max_chars: int = Field(default=40_000, ge=1)
    # Recorded as a control for downstream experiments. This harness invokes no model.
    model_config_id: str = Field(default="no-model", min_length=1)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _candidates(
    corpus: Corpus,
    blobs: LocalContentAddressedBlobStorage,
) -> tuple[ArtifactCandidate, ...]:
    output = []
    timestamp = datetime(2000, 1, 1, tzinfo=UTC)
    for index, document in enumerate(corpus.documents):
        stored = blobs.put_bytes(document.text.encode("utf-8"))
        snapshot_id = f"eval-snapshot-{index}"
        source = Source(
            source_id=document.id,
            investigation_id="eval-investigation",
            canonical_url=AnyHttpUrl(f"https://archive.invalid/documents/{index}"),
            title=document.title or document.id,
            source_type=SourceType.OTHER,
            discovered_at=timestamp,
        )
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source_id=document.id,
            run_id="eval-run",
            retrieved_at=timestamp,
            raw_blob_ref=stored.ref,
            raw_sha256=stored.ref.sha256,
            cleaned_blob_ref=stored.ref,
            cleaned_sha256=stored.ref.sha256,
            mime_type="text/plain",
            encoding="utf-8",
            content_size=stored.size_bytes,
            parse_status=ParseStatus.PARSED,
            parser_name="archive-eval",
            parser_version="1",
            normalizer_version="identity-v1",
            evidence_eligible=True,
        )
        artifact = DocumentArtifact(
            artifact_id=f"eval-artifact-{index}",
            snapshot_id=snapshot_id,
            artifact_type=(
                ArtifactType.PDF_PAGE_TEXT if document.page else ArtifactType.PLAIN_TEXT
            ),
            blob_ref=stored.ref,
            sha256=stored.ref.sha256,
            processor_name="archive-eval",
            processor_version="identity-v1",
            page_number=document.page,
            created_at=timestamp,
        )
        output.append(ArtifactCandidate(artifact=artifact, source=source, snapshot=snapshot))
    return tuple(output)


def _covered(label: SpanLabel, views: tuple[ArtifactView, ...]) -> bool:
    # Adjacent excerpts may jointly cover a label; overlaps never count twice.
    cursor = label.start
    ranges = sorted(
        (view.locator.start, view.locator.end)
        for view in views
        if view.source_key == label.document_id
    )
    for start, end in ranges:
        if start > cursor:
            break
        cursor = max(cursor, end)
        if cursor >= label.end:
            return True
    return False


def _score(case: EvaluationCase, views: tuple[ArtifactView, ...]) -> dict[str, Any]:
    found = [label for label in case.labels if _covered(label, views)]
    by_stance = {}
    for stance in ("supports", "contradicts"):
        total = sum(label.stance == stance for label in case.labels)
        matched = sum(label.stance == stance for label in found)
        by_stance[stance] = {
            "matched": matched,
            "total": total,
            "recall": matched / total if total else None,
        }
    return {
        "matched_spans": len(found),
        "labeled_spans": len(case.labels),
        "span_recall": len(found) / len(case.labels) if case.labels else None,
        "stance_recall": by_stance,
        "selected_chars": sum(len(view.excerpt) for view in views),
        "selected_documents": len({view.source_key for view in views}),
        "selected_excerpts": len(views),
        # Keep the exact potential model input, location and hashes for reproduction.
        "selection": [view.model_dump(mode="json") for view in views],
    }


def compare(corpus: Corpus, config: EvaluationConfig | None = None) -> dict[str, Any]:
    config = config or EvaluationConfig()
    serialized = json.dumps(corpus.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    archive = [
        {"id": document.id, "sha256": _digest(document.text), "page": document.page}
        for document in corpus.documents
    ]
    rows: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="marketpulse-offline-eval-") as directory:
        blobs = LocalContentAddressedBlobStorage(Path(directory))
        candidates = _candidates(corpus, blobs)
        limits = {
            "max_artifacts": config.max_artifacts,
            "max_excerpts": config.max_excerpts,
            "max_chars": config.max_chars,
        }
        baseline = ArtifactSelector(blobs, **limits)
        retrieval = BM25ArtifactSelector(blobs, **limits)
        for case in corpus.cases:
            rows.append(
                {
                    "case_id": case.id,
                    "question": case.question,
                    "category": case.category,
                    "tags": list(case.tags),
                    "truncation": _score(case, baseline.select(candidates)),
                    "bm25": _score(case, retrieval.select(candidates, query=case.question)),
                }
            )
    totals = {}
    for strategy in ("truncation", "bm25"):
        matched = sum(row[strategy]["matched_spans"] for row in rows)
        labeled = sum(row[strategy]["labeled_spans"] for row in rows)
        totals[strategy] = {
            "matched_spans": matched,
            "labeled_spans": labeled,
            "micro_span_recall": matched / labeled if labeled else None,
            "selected_chars": sum(row[strategy]["selected_chars"] for row in rows),
        }
    return {
        "schema_version": "archive-eval-result-v1",
        "dataset_kind": corpus.dataset_kind,
        "corpus_sha256": _digest(serialized),
        "archive": archive,
        "config": config.model_dump(),
        "model_calls": 0,
        "network_calls": 0,
        "scope": "retrieval coverage only; no conclusion-quality or maturity claim",
        "cases": rows,
        "totals": totals,
    }
