from __future__ import annotations

import asyncio
import json
import time

from ..contracts import CallContext, QuantAdapter, canonical
from ..domain import DataRequest, DatasetSnapshot
from ..storage.snapshots import SnapshotStore
from .base import ProviderUnavailable
from .quality import crosscheck
from .recording import RecordingQuantDataPort


class FrozenDataService:
    def __init__(self, store: SnapshotStore, adapters: tuple[RecordingQuantDataPort, ...]) -> None:
        self.store, self.adapters = store, adapters

    async def fetch(
        self, request: DataRequest, context: CallContext, *, offline: bool = False
    ) -> DatasetSnapshot:
        cached = await asyncio.to_thread(self.store.find, request, stale=offline)
        if cached:
            return cached
        if offline or request.snapshot_id:
            raise ProviderUnavailable("requested frozen snapshot unavailable offline")
        started = time.monotonic()
        primary = None
        attempts = []
        check = {
            "status": "UNAVAILABLE",
            "claims_paused": True,
            "independence": "UNVERIFIED",
            "overlap": 0,
            "conflicts": [],
        }
        for index, port in enumerate(self.adapters):
            remaining = context.budget_seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            child = context.model_copy(
                update={
                    "logical_key": context.logical_key + ":" + port.adapter.provider,
                    "ordinal": context.ordinal + index,
                    "budget_seconds": min(remaining, 45),
                }
            )
            try:
                result = await port.fetch(request, child)
            except (ProviderUnavailable, TimeoutError, ConnectionError) as error:
                attempts.append({"provider": port.adapter.provider, "error": type(error).__name__})
                continue
            attempts.append(
                {
                    "provider": result.provider,
                    "upstream": result.upstream,
                    "asof": result.request.asof.isoformat(),
                    "adjustment": result.request.adjustment,
                    "units": result.units,
                }
            )
            if primary is None:
                primary = result
                if request.dataset != "daily":
                    break
            else:
                check = crosscheck(
                    json.loads(primary.records_json), json.loads(result.records_json)
                )
                check["secondary_provider"] = result.provider
                break
        if primary is None:
            raise ProviderUnavailable("all recorded providers exhausted")
        check["attempts"] = attempts
        flags = set(primary.quality_flags)
        if request.dataset == "daily":
            if check["status"] == "CONFLICT":
                flags.add("crosscheck_conflict_claims_paused")
            elif check["status"] != "MATCH":
                flags.add("crosscheck_unavailable_claims_paused")
        primary = primary.model_copy(
            update={"crosscheck_json": canonical(check), "quality_flags": tuple(sorted(flags))}
        )
        return await asyncio.to_thread(self.store.freeze, primary)


def recorded_chain(
    adapters: tuple[QuantAdapter, ...], journal
) -> tuple[RecordingQuantDataPort, ...]:
    """P0 order: BaoStock, Tencent, Eastmoney; never call an unrecorded adapter."""
    order = {"baostock": 0, "akshare_tencent": 1, "akshare_eastmoney": 2, "akshare_sina": 3}
    return tuple(
        RecordingQuantDataPort(adapter, journal)
        for adapter in sorted(adapters, key=lambda item: order.get(item.provider, 99))
    )
