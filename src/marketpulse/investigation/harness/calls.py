from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.domain.runtime import CallBinding
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.harness.uow import UnitOfWork
from marketpulse.investigation.persistence.models import RunBudgetRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository
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
from marketpulse.investigation.recording.adapters import (
    CallContext,
    RecordingFetchAdapter,
    RecordingModelAdapter,
    RecordingSearchAdapter,
)
from marketpulse.investigation.recording.canonical import canonical_request, request_fingerprint
from marketpulse.investigation.recording.errors import ExternalCallError, ReplayCacheMissError
from marketpulse.investigation.recording.store import RecordedCallStore

T = TypeVar("T", bound=BaseModel)
RecordedCall = RecordedToolCall | RecordedModelCall


class ReplayBindingMismatchError(ExternalCallError):
    code = "REPLAY_BINDING_MISMATCH"


@dataclass(frozen=True, slots=True)
class StepCallSite:
    run_id: str
    step_id: str
    logical_step_key: str
    call_site_key: str
    call_ordinal: int


class BoundExternalCalls:
    """Durable call-site binding; exact recorded payloads are reused on retry/replay."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        recordings: RecordedCallStore,
        source_run_id: str | None = None,
        live_search: SearchPort | None = None,
        live_fetch: FetchPort | None = None,
        live_model: ModelPort | None = None,
    ) -> None:
        self.sessions = sessions
        self.repository = repository
        self.recordings = recordings
        self.source_run_id = source_run_id
        self.live_search = live_search
        self.live_fetch = live_fetch
        self.live_model = live_model

    def _binding(self, site: StepCallSite) -> CallBinding | None:
        with self.sessions() as session:
            return self.repository.binding_for_site(
                session,
                site.run_id,
                site.logical_step_key,
                site.call_site_key,
                site.call_ordinal,
            )

    def _candidate(
        self, site: StepCallSite, operation: str, fingerprint: str, kind: str
    ) -> RecordedCall | None:
        source = self.source_run_id or site.run_id
        calls: list[RecordedCall]
        if kind == "MODEL":
            calls = list(
                self.recordings.replayable_model_calls(
                    run_id=source, operation=operation, request_fingerprint=fingerprint
                )
            )
        else:
            calls = list(
                self.recordings.replayable_tool_calls(
                    run_id=source, operation=operation, request_fingerprint=fingerprint
                )
            )
        for call in calls:
            if (
                call.metadata.get("logical_step_key") == site.logical_step_key
                and call.metadata.get("call_site_key") == site.call_site_key
                and call.metadata.get("call_ordinal") == site.call_ordinal
            ):
                return call
        return None

    def _check(
        self,
        *,
        site: StepCallSite,
        operation: str,
        fingerprint: str,
        request: BaseModel,
        schema_version: str,
        prompt_version: str | None,
        config_version: str,
        call: RecordedCall,
        binding: CallBinding | None,
    ) -> bytes:
        if (
            call.operation != operation
            or call.request_fingerprint != fingerprint
            or call.schema_version != schema_version
            or call.prompt_version != prompt_version
            or call.config_version != config_version
            or call.metadata.get("logical_step_key") != site.logical_step_key
            or call.metadata.get("call_site_key") != site.call_site_key
            or call.metadata.get("call_ordinal") != site.call_ordinal
        ):
            raise ReplayBindingMismatchError("recorded call identity or version changed")
        if binding is not None and (
            binding.recorded_call_id != call.call_id
            or binding.call_kind != ("MODEL" if operation == "model.generate" else "TOOL")
            or binding.request_fingerprint != fingerprint
            or binding.operation != operation
            or binding.schema_version != schema_version
            or binding.prompt_version != prompt_version
            or binding.config_version != config_version
        ):
            raise ReplayBindingMismatchError("durable binding does not match request")
        expected = canonical_request(operation, request)
        if self.recordings.read_payload(call.request_blob_ref) != expected:
            raise ReplayBindingMismatchError("recorded request bytes changed")
        if call.response_blob_ref is None:
            raise ReplayCacheMissError(operation=operation, request_fingerprint=fingerprint)
        return self.recordings.read_payload(call.response_blob_ref)

    def _reserve(self, run_id: str, operation: str) -> None:
        field = {
            "search": ("search_calls_used", "max_search_calls"),
            "fetch": ("fetch_calls_used", "max_fetch_calls"),
            "model.generate": ("model_calls_used", "max_model_calls"),
        }[operation]
        with UnitOfWork(self.sessions, self.repository) as work:
            used = getattr(RunBudgetRow, field[0])
            maximum = getattr(RunBudgetRow, field[1])
            result = work.session.execute(
                update(RunBudgetRow)
                .where(RunBudgetRow.run_id == run_id, used < maximum)
                .values(**{field[0]: used + 1, "updated_at": datetime.now(UTC)})
            )
            if getattr(result, "rowcount", None) != 1:
                raise RunBudgetExceededError(f"{operation} call budget exhausted")
            work.commit()

    def _bind(
        self,
        *,
        site: StepCallSite,
        operation: str,
        fingerprint: str,
        kind: str,
        schema_version: str,
        prompt_version: str | None,
        config_version: str,
        call: RecordedCall,
        tokens: int = 0,
    ) -> None:
        with UnitOfWork(self.sessions, self.repository) as work:
            existing = self.repository.binding_for_site(
                work.session,
                site.run_id,
                site.logical_step_key,
                site.call_site_key,
                site.call_ordinal,
            )
            if existing is not None:
                if existing.recorded_call_id != call.call_id:
                    raise ReplayBindingMismatchError("call site was bound to another call")
                return
            values: dict[str, Any] = {
                "tokens_used": RunBudgetRow.tokens_used + tokens,
                "updated_at": datetime.now(UTC),
            }
            criteria = [
                RunBudgetRow.run_id == site.run_id,
                RunBudgetRow.tokens_used + tokens <= RunBudgetRow.max_tokens,
            ]
            if self.source_run_id is not None:
                field = {
                    "search": ("search_calls_used", "max_search_calls"),
                    "fetch": ("fetch_calls_used", "max_fetch_calls"),
                    "model.generate": ("model_calls_used", "max_model_calls"),
                }[operation]
                used = getattr(RunBudgetRow, field[0])
                maximum = getattr(RunBudgetRow, field[1])
                criteria.append(used < maximum)
                values[field[0]] = used + 1
            result = work.session.execute(update(RunBudgetRow).where(*criteria).values(**values))
            if getattr(result, "rowcount", None) != 1:
                raise RunBudgetExceededError("call or token budget exhausted")
            work.add(
                CallBinding(
                    binding_id=f"BIND-{uuid.uuid4().hex}",
                    run_id=site.run_id,
                    logical_step_key=site.logical_step_key,
                    call_site_key=site.call_site_key,
                    call_ordinal=site.call_ordinal,
                    request_fingerprint=fingerprint,
                    recorded_call_id=call.call_id,
                    call_kind=kind,
                    operation=operation,
                    schema_version=schema_version,
                    prompt_version=prompt_version,
                    config_version=config_version,
                    created_at=datetime.now(UTC),
                )
            )
            work.commit()

    def _resolve(
        self,
        *,
        site: StepCallSite,
        operation: str,
        request: BaseModel,
        kind: str,
        schema_version: str,
        prompt_version: str | None,
        config_version: str,
    ) -> tuple[RecordedCall | None, bytes | None, str]:
        fingerprint = request_fingerprint(operation, request)
        binding = self._binding(site)
        if binding is not None and binding.request_fingerprint != fingerprint:
            raise ReplayBindingMismatchError("call-site request fingerprint changed")
        call = self._candidate(site, operation, fingerprint, kind)
        if binding is not None and call is None:
            raise ReplayBindingMismatchError("bound recorded call is missing")
        if call is None:
            if self.source_run_id is not None:
                raise ReplayCacheMissError(operation=operation, request_fingerprint=fingerprint)
            return None, None, fingerprint
        payload = self._check(
            site=site,
            operation=operation,
            fingerprint=fingerprint,
            request=request,
            schema_version=schema_version,
            prompt_version=prompt_version,
            config_version=config_version,
            call=call,
            binding=binding,
        )
        return call, payload, fingerprint

    async def search(self, site: StepCallSite, request: SearchRequest) -> SearchResult:
        operation = "search"
        call, payload, fingerprint = self._resolve(
            site=site,
            operation=operation,
            request=request,
            kind="TOOL",
            schema_version=request.schema_version,
            prompt_version=None,
            config_version=request.config_version,
        )
        if call is None:
            if self.live_search is None:
                raise ReplayCacheMissError(operation=operation, request_fingerprint=fingerprint)
            self._reserve(site.run_id, operation)
            adapter = RecordingSearchAdapter(
                self.live_search,
                self.recordings,
                CallContext(
                    site.run_id,
                    site.step_id,
                    logical_step_key=site.logical_step_key,
                    call_site_key=site.call_site_key,
                    call_ordinal=site.call_ordinal,
                    record_attempt=self.repository.recorded_call_count(
                        run_id=site.run_id,
                        operation=operation,
                        fingerprint=fingerprint,
                        kind="TOOL",
                    )
                    + 1,
                ),
            )
            await adapter.search(request)
            call, payload, _ = self._resolve(
                site=site,
                operation=operation,
                request=request,
                kind="TOOL",
                schema_version=request.schema_version,
                prompt_version=None,
                config_version=request.config_version,
            )
        assert call is not None and payload is not None
        result = SearchResult.model_validate_json(payload)
        self._bind(
            site=site,
            operation=operation,
            fingerprint=fingerprint,
            kind="TOOL",
            schema_version=request.schema_version,
            prompt_version=None,
            config_version=request.config_version,
            call=call,
        )
        return result

    async def fetch(self, site: StepCallSite, request: FetchRequest) -> FetchResult:
        operation = "fetch"
        call, payload, fingerprint = self._resolve(
            site=site,
            operation=operation,
            request=request,
            kind="TOOL",
            schema_version=request.schema_version,
            prompt_version=None,
            config_version=request.config_version,
        )
        if call is None:
            if self.live_fetch is None:
                raise ReplayCacheMissError(operation=operation, request_fingerprint=fingerprint)
            self._reserve(site.run_id, operation)
            adapter = RecordingFetchAdapter(
                self.live_fetch,
                self.recordings,
                CallContext(
                    site.run_id,
                    site.step_id,
                    logical_step_key=site.logical_step_key,
                    call_site_key=site.call_site_key,
                    call_ordinal=site.call_ordinal,
                    record_attempt=self.repository.recorded_call_count(
                        run_id=site.run_id,
                        operation=operation,
                        fingerprint=fingerprint,
                        kind="TOOL",
                    )
                    + 1,
                ),
            )
            await adapter.fetch(request)
            call, payload, _ = self._resolve(
                site=site,
                operation=operation,
                request=request,
                kind="TOOL",
                schema_version=request.schema_version,
                prompt_version=None,
                config_version=request.config_version,
            )
        assert call is not None and payload is not None
        result = FetchResult.model_validate_json(payload)
        self._bind(
            site=site,
            operation=operation,
            fingerprint=fingerprint,
            kind="TOOL",
            schema_version=request.schema_version,
            prompt_version=None,
            config_version=request.config_version,
            call=call,
        )
        return result

    async def model(self, site: StepCallSite, request: ModelRequest[T]) -> StructuredModelResult[T]:
        operation = "model.generate"
        call, payload, fingerprint = self._resolve(
            site=site,
            operation=operation,
            request=request,
            kind="MODEL",
            schema_version=request.response_schema_version,
            prompt_version=request.prompt_version,
            config_version=request.config_version,
        )
        if call is None:
            if self.live_model is None:
                raise ReplayCacheMissError(operation=operation, request_fingerprint=fingerprint)
            self._reserve(site.run_id, operation)
            adapter = RecordingModelAdapter(
                self.live_model,
                self.recordings,
                CallContext(
                    site.run_id,
                    site.step_id,
                    logical_step_key=site.logical_step_key,
                    call_site_key=site.call_site_key,
                    call_ordinal=site.call_ordinal,
                    record_attempt=self.repository.recorded_call_count(
                        run_id=site.run_id,
                        operation=operation,
                        fingerprint=fingerprint,
                        kind="MODEL",
                    )
                    + 1,
                ),
            )
            await adapter.generate(request)
            call, payload, _ = self._resolve(
                site=site,
                operation=operation,
                request=request,
                kind="MODEL",
                schema_version=request.response_schema_version,
                prompt_version=request.prompt_version,
                config_version=request.config_version,
            )
        assert call is not None and payload is not None
        raw: dict[str, Any] = json.loads(payload)
        result = StructuredModelResult[T](
            output=request.response_model.model_validate(raw["output"]),
            provider=raw["provider"],
            model=raw["model"],
            usage=ModelUsage.model_validate(raw.get("usage", {})),
            response_id=raw.get("response_id"),
        )
        tokens = (result.usage.input_tokens or 0) + (result.usage.output_tokens or 0)
        self._bind(
            site=site,
            operation=operation,
            fingerprint=fingerprint,
            kind="MODEL",
            schema_version=request.response_schema_version,
            prompt_version=request.prompt_version,
            config_version=request.config_version,
            call=call,
            tokens=tokens,
        )
        return result
