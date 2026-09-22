from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import AnyHttpUrl, Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    BlobReference,
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)
from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus, SourceType
from marketpulse.investigation.domain.locators import EvidenceLocator


class Source(DomainModel):
    source_id: EntityId
    investigation_id: EntityId
    canonical_url: AnyHttpUrl
    title: NonEmptyText
    publisher: str | None = None
    organization: str | None = None
    source_type: SourceType
    is_official: bool = False
    is_first_hand: bool = False
    author: str | None = None
    published_at: datetime | None = None
    discovered_at: datetime
    origin_source_id: EntityId | None = None
    syndication_cluster_id: str | None = None


class SourceSnapshot(DomainModel):
    snapshot_id: EntityId
    source_id: EntityId
    run_id: EntityId
    retrieved_at: datetime
    raw_blob_ref: BlobReference
    raw_sha256: Sha256
    cleaned_blob_ref: BlobReference | None = None
    cleaned_sha256: Sha256 | None = None
    mime_type: NonEmptyText
    encoding: str | None = None
    content_size: int = Field(ge=0)
    http_status: int | None = Field(default=None, ge=100, le=599)
    parse_status: ParseStatus
    parser_name: NonEmptyText
    parser_version: NonEmptyText
    normalizer_version: NonEmptyText
    evidence_eligible: bool
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def blob_pairs_are_consistent(self) -> SourceSnapshot:
        if self.raw_blob_ref.sha256 != self.raw_sha256:
            raise ValueError("raw_sha256 must match raw_blob_ref")
        if (self.cleaned_blob_ref is None) != (self.cleaned_sha256 is None):
            raise ValueError("cleaned blob reference and hash must be provided together")
        if self.cleaned_blob_ref and self.cleaned_blob_ref.sha256 != self.cleaned_sha256:
            raise ValueError("cleaned_sha256 must match cleaned_blob_ref")
        if self.evidence_eligible and self.cleaned_blob_ref is None:
            raise ValueError("evidence-eligible snapshot requires cleaned content")
        return self


class DocumentArtifact(DomainModel):
    artifact_id: EntityId
    snapshot_id: EntityId
    artifact_type: ArtifactType
    blob_ref: BlobReference
    sha256: Sha256
    processor_name: NonEmptyText
    processor_version: NonEmptyText
    page_number: int | None = Field(default=None, ge=1)
    created_at: datetime

    @model_validator(mode="after")
    def blob_hash_matches(self) -> DocumentArtifact:
        if self.blob_ref.sha256 != self.sha256:
            raise ValueError("artifact sha256 must match blob_ref")
        if self.artifact_type is ArtifactType.PDF_PAGE_TEXT and self.page_number is None:
            raise ValueError("PDF page artifact requires page_number")
        return self


class Evidence(DomainModel):
    evidence_id: EntityId
    run_id: EntityId
    snapshot_id: EntityId
    artifact_id: EntityId | None = None
    content: NonEmptyText
    content_hash: Sha256
    locator: EvidenceLocator
    event_time: datetime | None = None
    extracted_at: datetime
    extractor_name: NonEmptyText
    extractor_version: NonEmptyText
    created_by_step_id: EntityId | None = None
    research_task_id: EntityId | None = None

    @model_validator(mode="after")
    def content_digest_matches(self) -> Evidence:
        digest = hashlib.sha256(self.content.encode()).hexdigest()
        if digest != self.content_hash:
            raise ValueError("content_hash must match UTF-8 evidence content")
        return self
