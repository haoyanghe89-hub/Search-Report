from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import Field

from .domain import (  # noqa: F401
    ArtifactBundle,
    ComputeInput,
    DataRequest,
    DataResult,
    FinancialFact,
    FrozenModel,
    MetricSpec,
    MetricValue,
    PricePoint,
    PriceSeries,
)


def canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def request_hash(request: DataRequest) -> str:
    return digest(request.model_dump(mode="json", exclude={"snapshot_id"}))


class CallContext(FrozenModel):
    logical_key: str
    ordinal: int = Field(ge=0)
    attempt: int = Field(ge=1)
    budget_seconds: float = Field(gt=0, le=120)


class QuantDataPort(Protocol):
    async def fetch(self, request: DataRequest, context: CallContext) -> DataResult: ...


class QuantAdapter(Protocol):
    provider: str
    upstream: str

    async def fetch(self, request: DataRequest, context: CallContext) -> DataResult: ...


class RecordedCall(FrozenModel):
    context: CallContext
    request_hash: str
    provider: str
    result: DataResult | None = None
    error: str | None = None


class CallJournal(Protocol):
    def append(self, call: RecordedCall) -> None: ...
    def find(self, context: CallContext) -> RecordedCall | None: ...
