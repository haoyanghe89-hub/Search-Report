from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from marketpulse.investigation.domain.runtime import ExecutionStep
from marketpulse.investigation.harness.calls import BoundExternalCalls, StepCallSite
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    ModelRequest,
    SearchRequest,
    SearchResult,
    StructuredModelResult,
)

T = TypeVar("T", bound=BaseModel)


class StepPortScope:
    """Creates ordinary Ports bound to one durable Harness Step and stable call-site keys."""

    def __init__(self, calls: BoundExternalCalls) -> None:
        self._calls = calls
        self._step: ExecutionStep | None = None

    def bind(self, step: ExecutionStep) -> None:
        self._step = step

    @property
    def step(self) -> ExecutionStep:
        if self._step is None:
            raise RuntimeError("StepPortScope is not bound")
        return self._step

    def _site(self, call_site_key: str, ordinal: int) -> StepCallSite:
        if self._step is None or self._step.logical_step_key is None:
            raise RuntimeError("StepPortScope is not bound")
        return StepCallSite(
            run_id=self._step.run_id,
            step_id=self._step.step_id,
            logical_step_key=self._step.logical_step_key,
            call_site_key=call_site_key,
            call_ordinal=ordinal,
        )

    def model(self, call_site_key: str) -> StepScopedModelPort:
        return StepScopedModelPort(self, call_site_key)

    def search(self, call_site_key: str) -> StepScopedSearchPort:
        return StepScopedSearchPort(self, call_site_key)

    def fetch(self, call_site_key: str) -> StepScopedFetchPort:
        return StepScopedFetchPort(self, call_site_key)


class StepScopedModelPort:
    def __init__(self, scope: StepPortScope, call_site_key: str) -> None:
        self._scope = scope
        self._call_site_key = call_site_key
        self._ordinal = 0

    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]:
        ordinal = self._ordinal
        self._ordinal += 1
        return await self._scope._calls.model(
            self._scope._site(self._call_site_key, ordinal), request
        )


class StepScopedSearchPort:
    def __init__(self, scope: StepPortScope, call_site_key: str) -> None:
        self._scope = scope
        self._call_site_key = call_site_key
        self._ordinal = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        ordinal = self._ordinal
        self._ordinal += 1
        return await self._scope._calls.search(
            self._scope._site(self._call_site_key, ordinal), request
        )


class StepScopedFetchPort:
    def __init__(self, scope: StepPortScope, call_site_key: str) -> None:
        self._scope = scope
        self._call_site_key = call_site_key
        self._ordinal = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        ordinal = self._ordinal
        self._ordinal += 1
        return await self._scope._calls.fetch(
            self._scope._site(self._call_site_key, ordinal), request
        )
