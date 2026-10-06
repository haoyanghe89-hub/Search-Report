import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from marketpulse.quant.contracts import CallContext, canonical
from marketpulse.quant.data.instruments import InstrumentMaster
from marketpulse.quant.data.normalize import normalize
from marketpulse.quant.data.pit import classify
from marketpulse.quant.data.quality import crosscheck
from marketpulse.quant.data.recording import (
    MemoryCallJournal,
    RecordingQuantDataPort,
    ReplayQuantDataPort,
)
from marketpulse.quant.domain import (
    DataRequest,
    DataResult,
    DataRights,
    DataRightsPolicy,
    Instrument,
    InstrumentAlias,
    PITLevel,
    RightsScope,
)

ID = "ins_test_entity_001"


def request(**changes):
    return DataRequest(
        **{
            **dict(
                instruments=(ID,),
                dataset="daily",
                start=date(2024, 6, 1),
                end=date(2024, 6, 14),
                asof=datetime(2024, 6, 15, tzinfo=UTC),
            ),
            **changes,
        }
    )


def instrument():
    return Instrument(
        instrument_id=ID,
        name="fixture",
        board="main",
        listed_at=date(1991, 4, 3),
        aliases=(InstrumentAlias(exchange="XSHE", code="000001", valid_from=date(1991, 4, 3)),),
        lifecycle_source="test",
    )


def result(provider="baostock", req=None, close=10):
    req = req or request()
    rows = [
        {
            "instrument_id": ID,
            "date": "2024-06-14",
            "open": close,
            "close": close,
            "high": close + 1,
            "low": close - 1,
            "volume": 100.0,
            "provisional": False,
        }
    ]
    return DataResult(
        provider=provider,
        upstream=provider,
        request=req,
        retrieved_at=datetime.now(UTC),
        records_json=canonical(rows),
        raw_records_json=canonical(rows),
        pit=PITLevel.PARTIAL,
        rights=DataRights(
            policy_id="unknown", provider=provider, upstream=provider, attribution=provider
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"asof": datetime(2024, 6, 15)},
        {"end": date(2024, 5, 31)},
        {"start": date(2010, 1, 1)},
        {"instruments": ("000001",)},
        {"adjustment": "qfq"},
        {"extra": True},
        {"end": date(2025, 1, 1)},
    ],
)
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)


def test_frozen_and_rights_fail_closed():
    value = request()
    with pytest.raises(ValidationError):
        value.end = date(2024, 6, 16)
    rights = result().rights.model_copy(update={"raw_export": True, "external_share": True})
    for action in ("raw_export", "external_share"):
        assert not DataRightsPolicy.allows(
            rights, action, datetime.now(UTC), RightsScope.INTERNAL_RESEARCH
        )
    rights = rights.model_copy(update={"entitlement": "licensed", "license_reference": "L1"})
    assert DataRightsPolicy.allows(
        rights, "raw_export", datetime.now(UTC), RightsScope.INTERNAL_RESEARCH
    )
    assert not DataRightsPolicy.allows(
        rights, "raw_export", datetime.now(UTC), RightsScope.LICENSED_SERVICE
    )


def test_code_lifecycle_overlap():
    master = InstrumentMaster((instrument(),))
    with pytest.raises(ValueError):
        master.add(instrument().model_copy(update={"instrument_id": "ins_other_entity_001"}))
    with pytest.raises(ValueError):
        master.alias(ID, date(1990, 1, 1))


@pytest.mark.parametrize(
    "provider,volume,turn",
    [
        ("baostock", "10000", "1"),
        ("akshare_tencent", 10000, 0.01),
        ("akshare_eastmoney", 100, 1),
    ],
)
def test_units_and_empty(provider, volume, turn):
    rows, units = normalize(
        [
            dict(
                date="2024-06-14",
                open="10",
                close="10",
                high="11",
                low="9",
                volume=volume,
                turnover=turn,
                turn=turn,
                pbMRQ="",
                isST="0",
                tradestatus="1",
            )
        ],
        request(),
        provider,
        ID,
    )
    assert rows[0]["volume"] == 10000
    assert rows[0]["turnover"] == 0.01
    assert rows[0]["pb_mrq"] is None
    assert dict(units)["volume"] == "share"


def test_financial_pit_and_null_not_zero():
    req = request(dataset="financial", start=date(2024, 1, 1), end=date(2024, 3, 31))
    rows, _ = normalize(
        [
            dict(
                statDate="2024-03-31", pubDate="2024-04-20", gpMargin="", netProfit="12", epsTTM="2"
            )
        ],
        req,
        "baostock",
        ID,
    )
    assert rows[0]["gross_margin"] is None
    assert classify("financial", "baostock", rows) == PITLevel.PARTIAL
    early = req.model_copy(update={"asof": datetime(2024, 4, 20, tzinfo=UTC)})
    assert not normalize(
        [dict(statDate="2024-03-31", pubDate="2024-04-20")], early, "baostock", ID
    )[0]
    assert classify("financial", "akshare_sina", [{"published_at": None}]) == PITLevel.UNAVAILABLE


def test_conflict_never_averages():
    left, right = (
        json.loads(result(close=10).records_json),
        json.loads(result(close=12).records_json),
    )
    check = crosscheck(left, right)
    assert check["claims_paused"] and check["status"] == "CONFLICT"
    assert left[0]["close"] == 10 and right[0]["close"] == 12


@pytest.mark.asyncio
async def test_record_replay_budget_identity():
    class Adapter:
        provider = upstream = "memory"
        calls = 0

        async def fetch(self, req, context):
            self.calls += 1
            return result(provider=self.provider, req=req)

    adapter, journal = Adapter(), MemoryCallJournal()
    port = RecordingQuantDataPort(adapter, journal)
    context = CallContext(logical_key="daily", ordinal=0, attempt=1, budget_seconds=1)
    original = await port.fetch(request(), context)
    assert await ReplayQuantDataPort(journal).fetch(request(), context) == original
    assert adapter.calls == 1
    with pytest.raises(ValueError):
        await port.fetch(request(), context)
    with pytest.raises(ValueError):
        await ReplayQuantDataPort(journal).fetch(request(fields=("close",)), context)
