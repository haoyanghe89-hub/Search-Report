from __future__ import annotations

from typing import Protocol

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.persistence.repositories import InvestigationRepository


class RecordedCallStore(Protocol):
    def put_payload(self, payload: bytes) -> BlobRef: ...

    def read_payload(self, ref: BlobRef) -> bytes: ...

    def add_tool_call(self, call: RecordedToolCall) -> None: ...

    def add_model_call(self, call: RecordedModelCall) -> None: ...

    def replayable_tool_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedToolCall]: ...

    def replayable_model_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedModelCall]: ...


class RepositoryRecordedCallStore:
    def __init__(self, repository: InvestigationRepository, blobs: BlobStoragePort) -> None:
        self._repository = repository
        self._blobs = blobs

    def put_payload(self, payload: bytes) -> BlobRef:
        return self._blobs.put_bytes(payload).ref

    def read_payload(self, ref: BlobRef) -> bytes:
        return self._blobs.get_bytes(ref)

    def add_tool_call(self, call: RecordedToolCall) -> None:
        self._repository.add(call)

    def add_model_call(self, call: RecordedModelCall) -> None:
        self._repository.add(call)

    def replayable_tool_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedToolCall]:
        return self._repository.list_replayable_tool_calls(
            run_id=run_id,
            operation=operation,
            request_fingerprint=request_fingerprint,
        )

    def replayable_model_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedModelCall]:
        return self._repository.list_replayable_model_calls(
            run_id=run_id,
            operation=operation,
            request_fingerprint=request_fingerprint,
        )
