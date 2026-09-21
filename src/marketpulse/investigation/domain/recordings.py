from __future__ import annotations

from datetime import datetime

from pydantic import Field, JsonValue, model_validator

from marketpulse.investigation.domain.base import (
    BlobReference,
    DomainModel,
    EntityId,
    NonEmptyText,
    Sha256,
)


class _RecordedCall(DomainModel):
    call_id: EntityId
    run_id: EntityId
    step_id: EntityId
    operation: NonEmptyText
    request_fingerprint: Sha256
    request_blob_ref: BlobReference
    request_hash: Sha256
    response_blob_ref: BlobReference
    response_hash: Sha256
    provider: NonEmptyText
    schema_version: NonEmptyText
    prompt_version: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    recorded_at: datetime

    @model_validator(mode="after")
    def blob_hashes_match(self) -> _RecordedCall:
        if self.request_blob_ref.sha256 != self.request_hash:
            raise ValueError("request_hash must match request_blob_ref")
        if self.response_blob_ref.sha256 != self.response_hash:
            raise ValueError("response_hash must match response_blob_ref")
        return self


class RecordedToolCall(_RecordedCall):
    tool_name: NonEmptyText


class RecordedModelCall(_RecordedCall):
    model: NonEmptyText
