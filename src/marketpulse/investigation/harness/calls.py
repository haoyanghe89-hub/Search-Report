from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.domain.runtime import CallBinding, RunBudget
from marketpulse.investigation.harness.model_call_journal import prepare_model_intent
from marketpulse.investigation.harness.model_retry import (
    ModelRetryExhaustedError,
    retryable_model_error,
)
from marketpulse.investigation.harness.model_routing import ModelRoutingPolicy
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.harness.stage_budget import (
    StageBudgetPolicy,
    VerificationBudgetPolicy,
    conservative_request_tokens,
)
from marketpulse.investigation.harness.uow import UnitOfWork
from marketpulse.investigation.persistence.models import (
    AuditEventRow,
    RecordedModelCallRow,
    RunBudgetRow,
)
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
from marketpulse.investigation.recording.diagnostics import provider_diagnostics
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
        authorized_unknown_intent_ids: frozenset[str] = frozenset(),
        pause_on_unknown_outcome: bool = False,
        model_budget_policy: StageBudgetPolicy | None = None,
        model_routing: ModelRoutingPolicy | None = None,
        model_retry_attempts: int = 0,
        model_retry_backoff_seconds: float = 1,
    ) -> None:
        self.sessions = sessions
        self.model_budget_policy = model_budget_policy
        self.model_routing = model_routing
        self.model_retry_attempts = model_retry_attempts
        self.model_retry_backoff_seconds = model_retry_backoff_seconds
        self.verification_budget_policy: VerificationBudgetPolicy | None = None
        self._inflight_tokens: dict[StepCallSite, int] = {}
        self.repository = repository
        self.recordings = recordings
        self.source_run_id = source_run_id
        self.live_search = live_search
        self.live_fetch = live_fetch
        self.live_model = live_model
        self.authorized_unknown_intent_ids = authorized_unknown_intent_ids
        self.pause_on_unknown_outcome = pause_on_unknown_outcome

    def verification_usage(self, run_id: str) -> tuple[int, int]:
        """Durable usage, including failed repairs; resumes do not reset this limit."""
        with self.sessions() as session:
            rows = session.scalars(
                select(RecordedModelCallRow).where(RecordedModelCallRow.run_id == run_id)
            ).all()
            records = [
                r for r in rows if r.prompt_version.rsplit(":", 1)[-1].startswith("verifier")
            ]
            intents = session.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.run_id == run_id, AuditEventRow.event_type == "MODEL_CALL_INTENT"
                )
            ).all()
            count = sum(
                str(r.metadata_payload.get("call_site_key", "")).startswith("verifier")
                for r in intents
            )
            tokens = 0
            for row in records:
                raw = (
                    json.loads(
                        self.recordings.read_payload(BlobRef.from_uri(row.response_blob_ref))
                    )
                    if row.response_blob_ref
                    else {}
                )
                usage = raw.get("usage", {})
                if usage.get("input_tokens") is not None and usage.get("output_tokens") is not None:
                    tokens += usage["input_tokens"] + usage["output_tokens"]
                else:
                    # No valid output/usage: conservatively count the serialized request
                    # plus its output ceiling, not zero-cost failed schema attempts.
                    request_bytes = self.recordings.read_payload(
                        BlobRef.from_uri(row.request_blob_ref)
                    )
                    request = json.loads(request_bytes).get("request", {})
                    tokens += (
                        usage.get("input_tokens")
                        if usage.get("input_tokens") is not None
                        else len(request_bytes)
                    ) + (
                        usage.get("output_tokens")
                        if usage.get("output_tokens") is not None
                        else request.get("max_output_tokens") or 0
                    )
        return max(count, len(records)), tokens

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

    def _reserve(self, run_id: str, operation: str, *, intent: AuditEvent | None = None) -> None:
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
            if intent is not None:
                work.add(intent)
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

    async def model(
        self,
        site: StepCallSite,
        request: ModelRequest[T],
        *,
        retry_unknown_outcome: bool = False,
    ) -> StructuredModelResult[T]:
        if self.model_routing is not None:
            request = self.model_routing.route(request)
        try:
            # All LIVE model roles are structured, read-only reasoning (no tools or
            # writes). Retrying unknown dispatches can ONLY duplicate model charges.
            # Each attempt still reserves budget and a new durable intent before I/O.
            for attempt in range(self.model_retry_attempts + 1):
                try:
                    return await self._model(
                        site,
                        request,
                        retry_unknown_outcome=retry_unknown_outcome
                        or (self.model_retry_attempts > 0 and attempt > 0),
                    )
                except Exception as error:
                    if self.model_retry_attempts == 0 or not retryable_model_error(error):
                        raise
                    with self.sessions() as session:
                        intents = session.scalars(
                            select(AuditEventRow).where(
                                AuditEventRow.run_id == site.run_id,
                                AuditEventRow.event_type == "MODEL_CALL_INTENT",
                            )
                        ).all()
                        dispatched = sum(
                            i.metadata_payload.get("logical_step_key") == site.logical_step_key
                            and i.metadata_payload.get("call_site_key") == site.call_site_key
                            and i.metadata_payload.get("call_ordinal") == site.call_ordinal
                            for i in intents
                        )
                    if (
                        attempt == self.model_retry_attempts
                        or dispatched >= self.model_retry_attempts + 1
                    ):
                        raise ModelRetryExhaustedError(
                            "网络不稳定，无法稳定连接模型服务；请检查网络/代理后重试。"
                        ) from error
                    self._inflight_tokens.pop(site, None)
                    await asyncio.sleep(self.model_retry_backoff_seconds * 2**attempt)
            raise AssertionError("unreachable model retry loop")
        finally:
            self._inflight_tokens.pop(site, None)

    async def _model(
        self,
        site: StepCallSite,
        request: ModelRequest[T],
        *,
        retry_unknown_outcome: bool = False,
    ) -> StructuredModelResult[T]:
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
            if self.verification_budget_policy is not None and request.prompt_version.rsplit(
                ":", 1
            )[-1].startswith("verifier"):
                count, tokens = self.verification_usage(site.run_id)
                inflight = sum(
                    value
                    for key, value in self._inflight_tokens.items()
                    if key.run_id == site.run_id and key.call_site_key.startswith("verifier")
                )
                cost = conservative_request_tokens(request)
                if not self.verification_budget_policy.admits(
                    calls=count, tokens=tokens, cost=cost, inflight_tokens=inflight
                ):
                    raise RunBudgetExceededError(
                        "VERIFICATION_LIMIT_REACHED: call/token ceiling; finish existing results",
                        required_tokens=cost,
                        role="verifier",
                    )
                self._inflight_tokens[site] = cost
            if self.model_budget_policy is not None:
                budget = self.repository.get(RunBudget, site.run_id)
                estimate = conservative_request_tokens(request)
                inflight = sum(
                    value
                    for key, value in self._inflight_tokens.items()
                    if key.run_id == site.run_id and key != site
                )
                role = request.prompt_version.rsplit(":", 1)[-1]
                if not self.model_budget_policy.admits(budget, role, estimate, inflight=inflight):
                    raise RunBudgetExceededError(
                        "stage model reservation: call or token headroom insufficient",
                        required_tokens=estimate,
                        role=role,
                    )
                # No await between this check/reservation and dispatch intent: one
                # owned event loop shares estimates across concurrent worker calls.
                self._inflight_tokens[site] = estimate
            intent, attempt = prepare_model_intent(
                self.sessions,
                run_id=site.run_id,
                logical_step_key=site.logical_step_key,
                call_site_key=site.call_site_key,
                call_ordinal=site.call_ordinal,
                fingerprint=fingerprint,
                next_record_attempt=self.repository.recorded_call_count(
                    run_id=site.run_id, operation=operation, fingerprint=fingerprint, kind="MODEL"
                )
                + 1,
                retry_unknown_outcome=retry_unknown_outcome,
                authorized_unknown_intent_ids=self.authorized_unknown_intent_ids,
            )
            self._reserve(site.run_id, operation, intent=intent)
            adapter = RecordingModelAdapter(
                self.live_model,
                self.recordings,
                CallContext(
                    site.run_id,
                    site.step_id,
                    logical_step_key=site.logical_step_key,
                    call_site_key=site.call_site_key,
                    call_ordinal=site.call_ordinal,
                    record_attempt=attempt,
                ),
            )
            try:
                await adapter.generate(request)
            except Exception as error:
                status = provider_diagnostics(error).get("http_status")
                if retryable_model_error(error):
                    # Unknown output usage is not free. Conservatively account the
                    # reserved request+output ceiling before considering another dispatch.
                    with self.sessions.begin() as session:
                        budget = session.get(RunBudgetRow, site.run_id)
                        if budget is not None:
                            budget.tokens_used = min(
                                budget.max_tokens,
                                budget.tokens_used + conservative_request_tokens(request),
                            )
                if self.pause_on_unknown_outcome and status not in {400, 401, 402, 403, 404, 422}:
                    # Reinspect the durable intent after the adapter records the failure.
                    # Prior consent never authorizes a new, ambiguous dispatch attempt.
                    prepare_model_intent(
                        self.sessions,
                        run_id=site.run_id,
                        logical_step_key=site.logical_step_key,
                        call_site_key=site.call_site_key,
                        call_ordinal=site.call_ordinal,
                        fingerprint=fingerprint,
                        next_record_attempt=attempt + 1,
                        retry_unknown_outcome=False,
                    )
                raise
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
