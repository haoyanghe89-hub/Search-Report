import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

from ..contracts import (
    CallContext,
    CallJournal,
    QuantAdapter,
    RecordedCall,
    canonical,
    request_hash,
)
from ..domain import DataRequest, DataResult
from .base import RECORDED_SCOPE


class MemoryCallJournal:
    def __init__(self) -> None:
        self.calls: list[RecordedCall] = []

    def append(self, call: RecordedCall) -> None:
        if self.find(call.context) is not None:
            raise ValueError("recorded call identity already exists")
        self.calls.append(call)

    def find(self, context: CallContext) -> RecordedCall | None:
        return next(
            (
                call
                for call in self.calls
                if (call.context.logical_key, call.context.ordinal, call.context.attempt)
                == (context.logical_key, context.ordinal, context.attempt)
            ),
            None,
        )


class FileCallJournal:
    """Immutable per-call records; atomic no-clobber publication, offline replay."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, context: CallContext) -> Path:
        identity = canonical([context.logical_key, context.ordinal, context.attempt])
        return self.directory / (hashlib.sha256(identity.encode()).hexdigest() + ".json")

    def append(self, call: RecordedCall) -> None:
        content = call.model_dump_json().encode()
        wrapper = canonical(
            {"sha256": hashlib.sha256(content).hexdigest(), "call": content.decode()}
        ).encode()
        with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(wrapper)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, self._path(call.context))
        except FileExistsError:
            raise ValueError("recorded call identity already exists") from None
        finally:
            temporary.unlink(missing_ok=True)

    def find(self, context: CallContext) -> RecordedCall | None:
        path = self._path(context)
        if not path.exists():
            return None
        value = json.loads(path.read_bytes())
        if hashlib.sha256(value["call"].encode()).hexdigest() != value["sha256"]:
            raise ValueError("call journal integrity failure")
        return RecordedCall.model_validate_json(value["call"])


class RecordingQuantDataPort:
    def __init__(self, adapter: QuantAdapter, journal: CallJournal) -> None:
        self.adapter, self.journal = adapter, journal

    async def fetch(self, request: DataRequest, context: CallContext) -> DataResult:
        if await asyncio.to_thread(self.journal.find, context) is not None:
            raise ValueError("use replay for an existing call identity")
        try:
            token = RECORDED_SCOPE.set(True)
            async with asyncio.timeout(context.budget_seconds):
                result = await self.adapter.fetch(request, context)
            if result.request != request or result.provider != self.adapter.provider:
                raise ValueError("adapter response provenance/request mismatch")
        except BaseException as error:
            await asyncio.to_thread(
                self.journal.append,
                RecordedCall(
                    context=context,
                    request_hash=request_hash(request),
                    provider=self.adapter.provider,
                    error=type(error).__name__,
                ),
            )
            raise
        finally:
            RECORDED_SCOPE.reset(token)
        await asyncio.to_thread(
            self.journal.append,
            RecordedCall(
                context=context,
                request_hash=request_hash(request),
                provider=self.adapter.provider,
                result=result,
            ),
        )
        return result


class ReplayQuantDataPort:
    def __init__(self, journal: CallJournal) -> None:
        self.journal = journal

    async def fetch(self, request: DataRequest, context: CallContext) -> DataResult:
        call = await asyncio.to_thread(self.journal.find, context)
        if call is None or call.request_hash != request_hash(request):
            raise ValueError("replay request/identity mismatch")
        if call.result is None:
            raise RuntimeError(call.error or "recorded failure")
        return call.result
