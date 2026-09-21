from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobIntegrityError, BlobRef
from marketpulse.investigation.domain.enums import ExternalCallStatus
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.ports.external import (
    ModelMessage,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResult,
    SearchResultItem,
    StructuredModelResult,
)
from marketpulse.investigation.recording.adapters import (
    CallContext,
    RecordingModelAdapter,
    RecordingSearchAdapter,
    ReplayModelAdapter,
    ReplaySearchAdapter,
)
from marketpulse.investigation.recording.errors import ReplayCacheMissError

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self.blobs = LocalContentAddressedBlobStorage(root)
        self.tool_calls: list[RecordedToolCall] = []
        self.model_calls: list[RecordedModelCall] = []
        self.corrupt_reads = False

    def put_payload(self, payload: bytes) -> BlobRef:
        return self.blobs.put_bytes(payload).ref

    def read_payload(self, ref: BlobRef) -> bytes:
        if self.corrupt_reads:
            raise BlobIntegrityError(ref)
        return self.blobs.get_bytes(ref)

    def add_tool_call(self, call: RecordedToolCall) -> None:
        self.tool_calls.append(call)

    def add_model_call(self, call: RecordedModelCall) -> None:
        self.model_calls.append(call)

    def replayable_tool_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedToolCall]:
        return [
            call
            for call in self.tool_calls
            if call.run_id == run_id
            and call.operation == operation
            and call.request_fingerprint == request_fingerprint
            and call.replayable
        ]

    def replayable_model_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedModelCall]:
        return [
            call
            for call in self.model_calls
            if call.run_id == run_id
            and call.operation == operation
            and call.request_fingerprint == request_fingerprint
            and call.replayable
        ]


class SearchFixture:
    calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        return SearchResult(
            items=(
                SearchResultItem(
                    title="Official report",
                    url="https://example.test/report",
                    snippet=request.query,
                    rank=1,
                ),
            ),
            provider="fixture-search",
            retrieved_at=NOW,
        )


class FailingSearch:
    async def search(self, request: SearchRequest) -> SearchResult:
        raise TimeoutError(request.query)


class ModelFixture:
    async def generate(self, request: ModelRequest[Answer]) -> StructuredModelResult[Answer]:
        return StructuredModelResult[Answer](
            output=Answer(value="typed"),
            provider="fixture-model-provider",
            model="fixture-model",
            usage=ModelUsage(input_tokens=3, output_tokens=1),
        )


def _context(run_id: str) -> CallContext:
    return CallContext(run_id=run_id, step_id=f"STEP-{run_id}")


@pytest.mark.asyncio
async def test_recording_search_persists_real_payload_refs_and_replays_typed_result(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "blobs")
    live = SearchFixture()
    request = SearchRequest(query="East Palestine", max_results=4)
    adapter = RecordingSearchAdapter(live, store, _context("RUN-LIVE"), clock=lambda: NOW)
    result = await adapter.search(request)

    call = store.tool_calls[0]
    assert result.items[0].title == "Official report"
    assert call.status is ExternalCallStatus.SUCCESS
    assert call.request_blob_ref != call.response_blob_ref
    assert store.read_payload(call.response_blob_ref)  # type: ignore[arg-type]

    replay = ReplaySearchAdapter(store, source_run_id="RUN-LIVE")
    replayed = await replay.search(request)
    assert replayed == result
    assert live.calls == 1


@pytest.mark.asyncio
async def test_recording_model_persists_and_replays_typed_output(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "blobs")
    request = ModelRequest[Answer](
        messages=(ModelMessage(role="user", content="answer"),),
        response_model=Answer,
        response_schema_version="answer-v1",
        prompt_version="prompt-v1",
    )
    result = await RecordingModelAdapter(
        ModelFixture(), store, _context("RUN-LIVE"), clock=lambda: NOW
    ).generate(request)
    replayed = await ReplayModelAdapter(store, source_run_id="RUN-LIVE").generate(request)

    assert result.output.value == "typed"
    assert replayed.output == Answer(value="typed")
    assert store.model_calls[0].model == "fixture-model"


@pytest.mark.asyncio
async def test_failed_call_is_recorded_but_not_replayable(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "blobs")
    request = SearchRequest(query="timeout")
    with pytest.raises(TimeoutError):
        await RecordingSearchAdapter(
            FailingSearch(), store, _context("RUN-LIVE"), clock=lambda: NOW
        ).search(request)

    assert store.tool_calls[0].status is ExternalCallStatus.TIMEOUT
    assert store.tool_calls[0].response_blob_ref is None
    with pytest.raises(ReplayCacheMissError):
        await ReplaySearchAdapter(store, source_run_id="RUN-LIVE").search(request)


@pytest.mark.asyncio
async def test_replay_miss_and_corrupt_blob_fail_closed(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "blobs")
    request = SearchRequest(query="exact")
    replay = ReplaySearchAdapter(store, source_run_id="RUN-LIVE")
    with pytest.raises(ReplayCacheMissError, match="REPLAY_CACHE_MISS"):
        await replay.search(request)

    await RecordingSearchAdapter(
        SearchFixture(), store, _context("RUN-LIVE"), clock=lambda: NOW
    ).search(request)
    store.corrupt_reads = True
    with pytest.raises(BlobIntegrityError, match="BLOB_INTEGRITY_ERROR"):
        await ReplaySearchAdapter(store, source_run_id="RUN-LIVE").search(request)
