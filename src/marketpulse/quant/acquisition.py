"""Bounded recorded acquisition; frozen inputs always win over runtime latest."""

import json
from datetime import date, datetime

from .contracts import CallContext
from .data.akshare_adapter import AkShareEastmoneyAdapter, AkShareTencentAdapter
from .data.baostock_adapter import BaoStockAdapter
from .data.calendar import CalendarVerification, VerifiedCalendar
from .data.instruments import InstrumentMaster
from .data.recording import FileCallJournal
from .data.service import FrozenDataService, recorded_chain
from .domain import DataRequest, Instrument
from .storage.models import InstrumentRow


async def acquire_inputs(runtime, run_id, plan):
    store = runtime.service.store
    with store.sessions() as session:
        instrument = Instrument.model_validate(
            session.get(InstrumentRow, plan.instrument).definition
        )
    master = InstrumentMaster((instrument,))
    exchange = master.alias(plan.instrument, plan.date_start).exchange
    financial_start = date(plan.date_end.year - 2, 1, 1)
    calendar_start = min(financial_start, plan.date_start)
    calendar = VerifiedCalendar(
        CalendarVerification(
            exchange=exchange,
            start=calendar_start,
            end=plan.date_end,
            sessions=(),
            source="awaiting_recorded_baostock_calendar",
            verified_at=plan.asof,
        )
    )
    journal = FileCallJournal(runtime.journal_root / run_id)
    ordinal = 0

    async def fetch(request, adapters):
        nonlocal ordinal
        context = CallContext(
            logical_key=run_id + ":" + request.dataset + ":" + str(ordinal),
            ordinal=ordinal,
            attempt=1,
            budget_seconds=45,
        )
        ordinal += 4
        service = FrozenDataService(store, recorded_chain(tuple(adapters), journal))
        return await service.fetch(request, context)

    base = dict(
        instruments=(plan.instrument,), start=calendar_start, end=plan.date_end, asof=plan.asof
    )
    c = await fetch(DataRequest(dataset="calendar", **base), [BaoStockAdapter(master, calendar)])
    sessions = tuple(
        date.fromisoformat(r["date"]) for r in json.loads(c.result.records_json) if r["is_session"]
    )
    calendar = VerifiedCalendar(
        CalendarVerification(
            exchange=exchange,
            start=calendar_start,
            end=plan.date_end,
            sessions=sessions,
            source=c.snapshot_id,
            verified_at=datetime.now(plan.asof.tzinfo),
        )
    )
    ids = [c.snapshot_id]
    for adjustment in ("raw", "qfq", "hfq"):
        request = DataRequest(
            instruments=(plan.instrument,),
            dataset="daily",
            start=plan.date_start,
            end=plan.date_end,
            asof=plan.asof,
            adjustment=adjustment,
            adjustment_anchor=plan.date_end if adjustment != "raw" else None,
        )
        try:
            snapshot = await fetch(
                request,
                [
                    BaoStockAdapter(master, calendar),
                    AkShareTencentAdapter(master, calendar),
                    AkShareEastmoneyAdapter(master, calendar),
                ],
            )
            ids.append(snapshot.snapshot_id)
        except (RuntimeError, TimeoutError):
            if adjustment in {"raw", plan.adjustment}:
                raise
    for dataset, fields in (
        ("financial", ("balance_sheet",)),
        ("financial", ("income_statement",)),
        ("valuation", ()),
    ):
        request = DataRequest(
            instruments=(plan.instrument,),
            dataset=dataset,
            start=financial_start if dataset == "financial" else plan.date_start,
            end=plan.date_end,
            asof=plan.asof,
            normalizer_version="3-parent-2",
            fields=fields,
        )
        try:
            snapshot = await fetch(request, [AkShareEastmoneyAdapter(master, calendar)])
            ids.append(snapshot.snapshot_id)
        except (RuntimeError, TimeoutError, ValueError):
            # Genuine missing fundamentals produce nulls and report limitations, not model values.
            continue
    return tuple(ids)
