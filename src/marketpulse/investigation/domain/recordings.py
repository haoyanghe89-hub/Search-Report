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
from marketpulse.investigation.domain.enums import ExternalCallStatus


class _RecordedCall(DomainModel):
    call_id: EntityId
    run_id: EntityId
    step_id: EntityId
    operation: NonEmptyText
    request_fingerprint: Sha256
    request_blob_ref: BlobReference
    request_hash: Sha256
    response_blob_ref: BlobReference | None = None
    response_hash: Sha256 | None = None
    provider: NonEmptyText
    schema_version: NonEmptyText
    prompt_version: str | None = None
    config_version: NonEmptyText
    attempt: int = Field(ge=1)
    status: ExternalCallStatus
    replayable: bool
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    recorded_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def blob_hashes_match(self) -> _RecordedCall:
        if self.request_blob_ref.sha256 != self.request_hash:
            raise ValueError("request_hash must match request_blob_ref")
        if (self.response_blob_ref is None) != (self.response_hash is None):
            raise ValueError("response blob reference and hash must be provided together")
        if self.response_blob_ref and self.response_blob_ref.sha256 != self.response_hash:
            raise ValueError("response_hash must match response_blob_ref")
        if self.completed_at < self.recorded_at:
            raise ValueError("completed_at cannot precede recorded_at")
        if self.status is ExternalCallStatus.SUCCESS and self.response_blob_ref is None:
            raise ValueError("successful call requires a complete response payload")
        if self.status is not ExternalCallStatus.SUCCESS and self.replayable:
            raise ValueError("failed call cannot be replayable")
        if self.replayable and self.response_blob_ref is None:
            raise ValueError("replayable call requires a complete response payload")
        return self


class RecordedToolCall(_RecordedCall):
    tool_name: NonEmptyText


class RecordedModelCall(_RecordedCall):
    model: NonEmptyText
