from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel, JsonValue, ValidationError

from marketpulse.investigation.domain.enums import ExternalCallStatus
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.ports.external import (
    FetchPort,
    FetchRequest,
    FetchResult,
    ModelPort,
    ModelRequest,
    ModelUsage,
    SearchPort,
    SearchRequest,
    SearchResult,
    StructuredModelResult,
)
from marketpulse.investigation.recording.canonical import (
    canonical_request,
    canonical_response,
    request_fingerprint,
)
from marketpulse.investigation.recording.errors import (
    InvalidProviderResponseError,
    RateLimitedError,
    ReplayCacheMissError,
    SecurityBlockedError,
)
from marketpulse.investigation.recording.store import RecordedCallStore

T = TypeVar("T", bound=BaseModel)
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _call_id() -> str:
    return f"CALL-{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class CallContext:
    run_id: str
    step_id: str
    provider: str = "unknown"
    logical_step_key: str | None = None
    call_site_key: str | None = None
    call_ordinal: int | None = None
    record_attempt: int | None = None

    def binding_metadata(self) -> dict[str, JsonValue]:
        if self.logical_step_key is None or self.call_site_key is None or self.call_ordinal is None:
            return {}
        return {
            "logical_step_key": self.logical_step_key,
            "call_site_key": self.call_site_key,
            "call_ordinal": self.call_ordinal,
        }


def _failure_status(error: BaseException) -> ExternalCallStatus:
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return ExternalCallStatus.TIMEOUT
    if isinstance(error, RateLimitedError):
        return ExternalCallStatus.RATE_LIMITED
    if isinstance(error, InvalidProviderResponseError):
        return ExternalCallStatus.INVALID_RESPONSE
    if isinstance(error, SecurityBlockedError):
        return ExternalCallStatus.SECURITY_BLOCKED
    if isinstance(error, asyncio.CancelledError):
        return ExternalCallStatus.CANCELLED
    return ExternalCallStatus.PROVIDER_ERROR


class _AttemptCounter:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, fingerprint: str) -> int:
        value = self._counts.get(fingerprint, 0) + 1
        self._counts[fingerprint] = value
        return value


class RecordingSearchAdapter:
    operation = "search"

    def __init__(
        self,
        live: SearchPort,
        store: RecordedCallStore,
        context: CallContext,
        *,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _call_id,
    ) -> None:
        self._live = live
        self._store = store
        self._context = context
        self._clock = clock
        self._id_factory = id_factory
        self._attempts = _AttemptCounter()

    async def search(self, request: SearchRequest) -> SearchResult:
        fingerprint = request_fingerprint(self.operation, request)
        request_ref = self._store.put_payload(canonical_request(self.operation, request))
        started = self._clock()
        attempt = self._context.record_attempt or self._attempts.next(fingerprint)
        try:
            result = SearchResult.model_validate(await self._live.search(request))
        except BaseException as error:
            self._record_failure(request, fingerprint, request_ref, started, attempt, error)
            raise
        response_ref = self._store.put_payload(canonical_response(result))
        self._store.add_tool_call(
            RecordedToolCall(
                call_id=self._id_factory(),
                run_id=self._context.run_id,
                step_id=self._context.step_id,
                operation=self.operation,
                request_fingerprint=fingerprint,
                request_blob_ref=request_ref,
                request_hash=request_ref.sha256,
                response_blob_ref=response_ref,
                response_hash=response_ref.sha256,
                tool_name="search-port",
                provider=result.provider,
                schema_version=request.schema_version,
                config_version=request.config_version,
                attempt=attempt,
                status=ExternalCallStatus.SUCCESS,
                replayable=True,
                metadata=self._context.binding_metadata(),
                recorded_at=started,
                completed_at=self._clock(),
            )
        )
        return result

    def _record_failure(
        self,
        request: SearchRequest,
        fingerprint: str,
        request_ref: Any,
        started: datetime,
        attempt: int,
        error: BaseException,
    ) -> None:
        status = _failure_status(error)
        self._store.add_tool_call(
            RecordedToolCall(
                call_id=self._id_factory(),
                run_id=self._context.run_id,
                step_id=self._context.step_id,
                operation=self.operation,
                request_fingerprint=fingerprint,
                request_blob_ref=request_ref,
                request_hash=request_ref.sha256,
                tool_name="search-port",
                provider=self._context.provider,
                schema_version=request.schema_version,
                config_version=request.config_version,
                attempt=attempt,
                status=status,
                replayable=False,
                error_code=getattr(error, "code", status.value),
                metadata={
                    **self._context.binding_metadata(),
                    "exception_type": type(error).__name__,
                },
                recorded_at=started,
                completed_at=self._clock(),
            )
        )


class RecordingFetchAdapter:
    operation = "fetch"

    def __init__(
        self,
        live: FetchPort,
        store: RecordedCallStore,
        context: CallContext,
        *,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _call_id,
    ) -> None:
        self._live = live
        self._store = store
        self._context = context
        self._clock = clock
        self._id_factory = id_factory
        self._attempts = _AttemptCounter()

    async def fetch(self, request: FetchRequest) -> FetchResult:
        fingerprint = request_fingerprint(self.operation, request)
        request_ref = self._store.put_payload(canonical_request(self.operation, request))
        started = self._clock()
        attempt = self._context.record_attempt or self._attempts.next(fingerprint)
        try:
            result = FetchResult.model_validate(await self._live.fetch(request))
        except BaseException as error:
            status = _failure_status(error)
            self._store.add_tool_call(
                RecordedToolCall(
                    call_id=self._id_factory(),
                    run_id=self._context.run_id,
                    step_id=self._context.step_id,
                    operation=self.operation,
                    request_fingerprint=fingerprint,
                    request_blob_ref=request_ref,
                    request_hash=request_ref.sha256,
                    tool_name="fetch-port",
                    provider=self._context.provider,
                    schema_version=request.schema_version,
                    config_version=request.config_version,
                    attempt=attempt,
                    status=status,
                    replayable=False,
                    error_code=getattr(error, "code", status.value),
                    metadata={
                        **self._context.binding_metadata(),
                        "exception_type": type(error).__name__,
                    },
                    recorded_at=started,
                    completed_at=self._clock(),
                )
            )
            raise
        response_ref = self._store.put_payload(canonical_response(result))
        self._store.add_tool_call(
            RecordedToolCall(
                call_id=self._id_factory(),
                run_id=self._context.run_id,
                step_id=self._context.step_id,
                operation=self.operation,
                request_fingerprint=fingerprint,
                request_blob_ref=request_ref,
                request_hash=request_ref.sha256,
                response_blob_ref=response_ref,
                response_hash=response_ref.sha256,
                tool_name="fetch-port",
                provider=self._context.provider,
                schema_version=request.schema_version,
                config_version=request.config_version,
                attempt=attempt,
                status=ExternalCallStatus.SUCCESS,
                replayable=True,
                metadata=self._context.binding_metadata(),
                recorded_at=started,
                completed_at=self._clock(),
            )
        )
        return result


class RecordingModelAdapter:
    operation = "model.generate"

    def __init__(
        self,
        live: ModelPort,
        store: RecordedCallStore,
        context: CallContext,
        *,
        clock: Clock = _utc_now,
        id_factory: IdFactory = _call_id,
    ) -> None:
        self._live = live
        self._store = store
        self._context = context
        self._clock = clock
        self._id_factory = id_factory
        self._attempts = _AttemptCounter()

    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]:
        fingerprint = request_fingerprint(self.operation, request)
        request_ref = self._store.put_payload(canonical_request(self.operation, request))
        started = self._clock()
        attempt = self._context.record_attempt or self._attempts.next(fingerprint)
        try:
            result = await self._live.generate(request)
            request.response_model.model_validate(result.output)
        except BaseException as error:
            status = _failure_status(error)
            self._store.add_model_call(
                RecordedModelCall(
                    call_id=self._id_factory(),
                    run_id=self._context.run_id,
                    step_id=self._context.step_id,
                    operation=self.operation,
                    request_fingerprint=fingerprint,
                    request_blob_ref=request_ref,
                    request_hash=request_ref.sha256,
                    provider=self._context.provider,
                    model=request.model_hint or "unknown",
                    schema_version=request.response_schema_version,
                    prompt_version=request.prompt_version,
                    config_version=request.config_version,
                    attempt=attempt,
                    status=status,
                    replayable=False,
                    error_code=getattr(error, "code", status.value),
                    metadata={
                        **self._context.binding_metadata(),
                        "exception_type": type(error).__name__,
                    },
                    recorded_at=started,
                    completed_at=self._clock(),
                )
            )
            raise
        response_ref = self._store.put_payload(canonical_response(result))
        self._store.add_model_call(
            RecordedModelCall(
                call_id=self._id_factory(),
                run_id=self._context.run_id,
                step_id=self._context.step_id,
                operation=self.operation,
                request_fingerprint=fingerprint,
                request_blob_ref=request_ref,
                request_hash=request_ref.sha256,
                response_blob_ref=response_ref,
                response_hash=response_ref.sha256,
                provider=result.provider,
                model=result.model,
                schema_version=request.response_schema_version,
                prompt_version=request.prompt_version,
                config_version=request.config_version,
                attempt=attempt,
                status=ExternalCallStatus.SUCCESS,
                replayable=True,
                metadata=self._context.binding_metadata(),
                recorded_at=started,
                completed_at=self._clock(),
            )
        )
        return result


class _ReplayCursor:
    def __init__(self) -> None:
        self._positions: dict[tuple[str, str], itertools.count[int]] = {}

    def next_index(self, operation: str, fingerprint: str) -> int:
        counter = self._positions.setdefault((operation, fingerprint), itertools.count())
        return next(counter)


def _payload_for_replay(
    store: RecordedCallStore,
    call: RecordedToolCall | RecordedModelCall,
    expected_request: bytes,
) -> bytes:
    if store.read_payload(call.request_blob_ref) != expected_request:
        raise ReplayCacheMissError(
            operation=call.operation,
            request_fingerprint=call.request_fingerprint,
        )
    if call.response_blob_ref is None:
        raise ReplayCacheMissError(
            operation=call.operation,
            request_fingerprint=call.request_fingerprint,
        )
    return store.read_payload(call.response_blob_ref)


class ReplaySearchAdapter:
    operation = RecordingSearchAdapter.operation

    def __init__(self, store: RecordedCallStore, *, source_run_id: str) -> None:
        self._store = store
        self._source_run_id = source_run_id
        self._cursor = _ReplayCursor()

    async def search(self, request: SearchRequest) -> SearchResult:
        fingerprint = request_fingerprint(self.operation, request)
        calls = self._store.replayable_tool_calls(
            run_id=self._source_run_id,
            operation=self.operation,
            request_fingerprint=fingerprint,
        )
        index = self._cursor.next_index(self.operation, fingerprint)
        if index >= len(calls):
            raise ReplayCacheMissError(operation=self.operation, request_fingerprint=fingerprint)
        payload = _payload_for_replay(
            self._store, calls[index], canonical_request(self.operation, request)
        )
        try:
            return SearchResult.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidProviderResponseError("recorded search response is invalid") from error


class ReplayFetchAdapter:
    operation = RecordingFetchAdapter.operation

    def __init__(self, store: RecordedCallStore, *, source_run_id: str) -> None:
        self._store = store
        self._source_run_id = source_run_id
        self._cursor = _ReplayCursor()

    async def fetch(self, request: FetchRequest) -> FetchResult:
        fingerprint = request_fingerprint(self.operation, request)
        calls = self._store.replayable_tool_calls(
            run_id=self._source_run_id,
            operation=self.operation,
            request_fingerprint=fingerprint,
        )
        index = self._cursor.next_index(self.operation, fingerprint)
        if index >= len(calls):
            raise ReplayCacheMissError(operation=self.operation, request_fingerprint=fingerprint)
        payload = _payload_for_replay(
            self._store, calls[index], canonical_request(self.operation, request)
        )
        try:
            return FetchResult.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidProviderResponseError("recorded fetch response is invalid") from error


class ReplayModelAdapter:
    operation = RecordingModelAdapter.operation

    def __init__(self, store: RecordedCallStore, *, source_run_id: str) -> None:
        self._store = store
        self._source_run_id = source_run_id
        self._cursor = _ReplayCursor()

    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]:
        fingerprint = request_fingerprint(self.operation, request)
        calls = self._store.replayable_model_calls(
            run_id=self._source_run_id,
            operation=self.operation,
            request_fingerprint=fingerprint,
        )
        index = self._cursor.next_index(self.operation, fingerprint)
        if index >= len(calls):
            raise ReplayCacheMissError(operation=self.operation, request_fingerprint=fingerprint)
        payload = _payload_for_replay(
            self._store, calls[index], canonical_request(self.operation, request)
        )
        try:
            raw = json.loads(payload)
            output = request.response_model.model_validate(raw["output"])
            return StructuredModelResult[T](
                output=output,
                provider=raw["provider"],
                model=raw["model"],
                usage=ModelUsage.model_validate(raw.get("usage", {})),
                response_id=raw.get("response_id"),
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise InvalidProviderResponseError("recorded model response is invalid") from error
