import asyncio
import json
from datetime import UTC, date, datetime

import pytest

from marketpulse.quant.contracts import CallContext, canonical
from marketpulse.quant.data.adjustments import anchored_prices
from marketpulse.quant.data.baostock_adapter import BaoStockAdapter
from marketpulse.quant.data.base import ProviderUnavailable
from marketpulse.quant.data.calendar import CalendarVerification, VerifiedCalendar
from marketpulse.quant.data.instruments import InstrumentMaster
from marketpulse.quant.data.normalize import normalize
from marketpulse.quant.data.recording import (
    FileCallJournal,
    MemoryCallJournal,
    RecordingQuantDataPort,
    ReplayQuantDataPort,
)
from marketpulse.quant.domain import InstrumentStatus, TradingRule
from tests.unit.quant.test_contracts_data import ID, instrument, request, result


def calendar():
    return VerifiedCalendar(
        CalendarVerification(
            exchange="XSHE",
            start=date(2024, 1, 1),
            end=date(2024, 6, 14),
            sessions=(date(2024, 4, 22), date(2024, 6, 14)),
            source="test recorded schedule",
            verified_at=datetime.now(UTC),
        )
    )


def context(key="test", budget=2):
    return CallContext(logical_key=key, ordinal=0, attempt=1, budget_seconds=budget)


@pytest.mark.parametrize("adjustment,expected", [("qfq", [5, 10]), ("hfq", [10, 20])])
def test_multibar_anchor_and_no_future_factor(adjustment, expected):
    rows = [dict(date="2024-06-13", close=10), dict(date="2024-06-14", close=10)]
    factors = [
        dict(dividOperateDate="2024-01-01", foreAdjustFactor="0.5", backAdjustFactor="1"),
        dict(dividOperateDate="2024-06-14", foreAdjustFactor="1", backAdjustFactor="2"),
        dict(dividOperateDate="2025-01-01", foreAdjustFactor="9", backAdjustFactor="9"),
    ]
    values = anchored_prices(
        rows, factors, request(adjustment=adjustment, adjustment_anchor=date(2024, 6, 14))
    )
    assert [r["close"] for r in values] == expected
    assert rows[0]["close"] == 10


@pytest.mark.parametrize("volume_unit,volume", [("hand", 100), ("share", 10000)])
def test_tencent_explicit_unit_metadata(volume_unit, volume):
    rows, _ = normalize(
        [dict(date="2024-06-14", volume=volume)],
        request(),
        "akshare_tencent",
        ID,
        {"volume": volume_unit},
    )
    assert rows[0]["volume"] == 10000


def test_versioned_t1_and_status():
    rule = TradingRule(
        version="fixture:1",
        exchange="XSHE",
        board="main",
        status="normal",
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 12, 31),
        source="fixture reference",
    )
    state = InstrumentStatus(
        effective_from=date(2024, 6, 14), suspended=True, is_st=True, source="fixture history"
    )
    master = InstrumentMaster(
        (instrument().model_copy(update={"rules": (rule,), "statuses": (state,)}),)
    )
    assert master.rule(ID, date(2024, 6, 14), "normal").settlement_days == 1
    assert master.status(ID, date(2024, 6, 14)).suspended
    assert master.status(ID, date(2024, 6, 13)) is None
    with pytest.raises(ValueError):
        master.rule(ID, date(2025, 1, 1), "normal")


def test_calendar_closed_and_out_of_verified_range():
    value = calendar()
    assert not value.complete(date(2024, 6, 14), datetime(2024, 6, 14, 6, tzinfo=UTC))
    assert value.complete(date(2024, 6, 14), datetime(2024, 6, 14, 7, tzinfo=UTC))
    with pytest.raises(ValueError):
        value.sessions(date(2030, 1, 1), date(2030, 1, 2))


@pytest.mark.asyncio
async def test_sdk_recording_gate_and_provisional(monkeypatch):
    adapter = BaoStockAdapter(InstrumentMaster((instrument(),)), calendar())
    raw = dict(
        date="2024-06-14",
        open="10",
        close="10",
        high="11",
        low="9",
        volume="100",
        tradestatus="1",
        isST="0",
    )

    async def fake_call(query, budget):
        return {"rows": [raw]}

    monkeypatch.setattr(adapter, "_call", fake_call)
    with pytest.raises(RuntimeError):
        await adapter.fetch(request(), context())
    journal = MemoryCallJournal()
    port = RecordingQuantDataPort(adapter, journal)
    req = request(asof=datetime(2024, 6, 14, 6, tzinfo=UTC))
    with pytest.raises(ProviderUnavailable):
        await port.fetch(req, context())
    assert journal.calls[0].error == "ProviderUnavailable"
    provisional = await port.fetch(
        req.model_copy(update={"complete_sessions_only": False}), context("provisional")
    )
    assert json.loads(provisional.records_json)[0]["provisional"]


@pytest.mark.asyncio
async def test_financial_next_verified_session_and_missing_bank_fields(monkeypatch):
    adapter = BaoStockAdapter(InstrumentMaster((instrument(),)), calendar())

    async def fake_call(query, budget):
        return {
            "rows": [
                dict(
                    statDate="2024-03-31",
                    pubDate="2024-04-20",
                    gpMargin="",
                    MBRevenue="",
                    netProfit="14932000000",
                    epsTTM="2.41",
                )
            ]
        }

    monkeypatch.setattr(adapter, "_call", fake_call)
    value = await RecordingQuantDataPort(adapter, MemoryCallJournal()).fetch(
        request(dataset="financial", start=date(2024, 1, 1), end=date(2024, 3, 31)), context()
    )
    row = json.loads(value.records_json)[0]
    assert row["available_at"] == "2024-04-22T09:30:00+08:00"
    assert row["gross_margin"] is None and row["revenue"] is None
    assert row["revision_id"] == "unknown" and value.pit.value == "PARTIAL"


@pytest.mark.asyncio
async def test_file_journal_replay_and_tamper(tmp_path):
    class Adapter:
        provider = upstream = "baostock"

        async def fetch(self, req, context):
            return result(req=req)

    journal = FileCallJournal(tmp_path / "calls")
    expected = await RecordingQuantDataPort(Adapter(), journal).fetch(request(), context())
    reopened = FileCallJournal(tmp_path / "calls")
    assert await ReplayQuantDataPort(reopened).fetch(request(), context()) == expected
    path = next((tmp_path / "calls").glob("*.json"))
    value = json.loads(path.read_text())
    value["call"] += " "
    path.write_text(canonical(value))
    with pytest.raises(ValueError):
        await ReplayQuantDataPort(reopened).fetch(request(), context())


@pytest.mark.asyncio
async def test_budget_cancellation_recorded():
    class Adapter:
        provider = upstream = "baostock"

        async def fetch(self, req, context):
            await asyncio.sleep(10)

    journal = MemoryCallJournal()
    with pytest.raises(TimeoutError):
        await RecordingQuantDataPort(Adapter(), journal).fetch(request(), context(budget=0.01))
    assert journal.calls[0].error == "TimeoutError"
