"""Task M live acceptance: recorded network data -> immutable snapshots -> offline hit.

No metrics, backtests, charts, LLM or HTTP contract changes. Outputs are private
research fixtures; their raw data rights remain unknown, not externally exportable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.quant.contracts import CallContext, canonical
from marketpulse.quant.data.akshare_adapter import (
    AkShareEastmoneyAdapter,
    AkShareTencentAdapter,
)
from marketpulse.quant.data.baostock_adapter import BaoStockAdapter
from marketpulse.quant.data.calendar import CalendarVerification, VerifiedCalendar
from marketpulse.quant.data.instruments import InstrumentMaster
from marketpulse.quant.data.recording import FileCallJournal, RecordingQuantDataPort
from marketpulse.quant.data.service import FrozenDataService, recorded_chain
from marketpulse.quant.domain import DataRequest, Instrument, InstrumentAlias
from marketpulse.quant.storage.reader import read_snapshot
from marketpulse.quant.storage.snapshots import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
START, END = date(2024, 5, 20), date(2024, 6, 14)
ASOF = datetime(2024, 6, 15, tzinfo=UTC)
CASES = (("000001", "XSHE"), ("600519", "XSHG"), ("000333", "XSHE"))


async def run(output: Path, supplementary: bool) -> None:
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    journal = FileCallJournal(output / "calls")
    url = "sqlite:///" + (output / "metadata.sqlite").as_posix()
    config = Config(ROOT / "alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_investigation_engine(url)
    store = SnapshotStore(
        create_session_factory(engine), LocalContentAddressedBlobStorage(output / "blobs")
    )
    summary = {
        "started_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "range": [START.isoformat(), END.isoformat()],
        "cases": [],
    }
    for index, (code, exchange) in enumerate(CASES):
        evidence = {"code": code, "exchange": exchange}
        summary["cases"].append(evidence)
        try:
            stable = (
                "ins_" + uuid.uuid5(uuid.NAMESPACE_URL, f"marketpulse:CN:{exchange}:{code}:v1").hex
            )
            # Bootstrap alias only; query_stock_basic replaces unknown lifecycle before publication.
            bootstrap = Instrument(
                instrument_id=stable,
                name=code,
                board="main",
                listed_at=date(1990, 1, 1),
                lifecycle_source="bootstrap_unverified",
                aliases=(
                    InstrumentAlias(exchange=exchange, code=code, valid_from=date(1990, 1, 1)),
                ),
            )
            master = InstrumentMaster((bootstrap,))
            placeholder = VerifiedCalendar(
                CalendarVerification(
                    exchange=exchange,
                    start=START,
                    end=END,
                    sessions=(),
                    source="unverified_bootstrap_NOT_FOR_DAILY",
                    verified_at=datetime.now(UTC),
                )
            )
            req = DataRequest(
                instruments=(stable,),
                dataset="calendar",
                start=date(2024, 1, 1),
                end=END,
                asof=ASOF,
            )
            ordinal = index * 100

            def context(label, code=code):
                nonlocal ordinal
                ordinal += 1
                return CallContext(
                    logical_key=f"{code}:{label}", ordinal=ordinal, attempt=1, budget_seconds=100
                )

            port = RecordingQuantDataPort(BaoStockAdapter(master, placeholder), journal)
            calendar_result = await port.fetch(req, context("calendar"))
            sessions = tuple(
                date.fromisoformat(row["date"])
                for row in json.loads(calendar_result.records_json)
                if row["is_session"]
            )
            calendar = VerifiedCalendar(
                CalendarVerification(
                    exchange=exchange,
                    start=date(2024, 1, 1),
                    end=END,
                    sessions=sessions,
                    source="BaoStock recorded schedule; provider provenance, not official proof",
                    # Must cover announcement visibility as well as daily price dates.
                    verified_at=datetime.now(UTC),
                )
            )
            basics = await port.fetch(
                req.model_copy(update={"dataset": "instrument_master"}), context("instrument")
            )
            basic = json.loads(basics.records_json)[0]
            if basic["type"] != "1" or not basic["listed_at"]:
                raise ValueError("not ordinary equity or lifecycle unavailable")
            actual = Instrument(
                instrument_id=stable,
                name=basic["name"],
                board="main",
                listed_at=date.fromisoformat(basic["listed_at"]),
                delisted_at=date.fromisoformat(basic["delisted_at"])
                if basic["delisted_at"]
                else None,
                lifecycle_source="BaoStock query_stock_basic (current state)",
                aliases=(
                    InstrumentAlias(
                        exchange=exchange,
                        code=code,
                        valid_from=date.fromisoformat(basic["listed_at"]),
                    ),
                ),
            )
            master = InstrumentMaster((actual,))
            store.register(actual)
            for auxiliary in (calendar_result, basics):
                await asyncio.to_thread(store.freeze, auxiliary)
            try:
                evidence["calendar_library_disagreements"] = [
                    day.isoformat() for day in calendar.compare_library()
                ]
            except Exception as error:
                evidence["calendar_library_error"] = type(error).__name__
            adapters = (
                BaoStockAdapter(master, calendar),
                AkShareTencentAdapter(master, calendar),
                AkShareEastmoneyAdapter(master, calendar),
            )
            service = FrozenDataService(store, recorded_chain(adapters, journal))
            daily = req.model_copy(update={"dataset": "daily", "start": START})
            snapshot = await service.fetch(daily, context("daily"))
            offline = await service.fetch(
                daily.model_copy(update={"snapshot_id": snapshot.snapshot_id}),
                context("offline"),
                offline=True,
            )
            # Query only by frozen ID, with bounded read-only DuckDB.
            read_rows = await asyncio.to_thread(read_snapshot, store, snapshot, stable)
            evidence.update(
                status="OK",
                instrument_id=stable,
                snapshot_id=snapshot.snapshot_id,
                manifest_ref=snapshot.manifest_ref,
                rows=snapshot.row_count,
                provider=snapshot.result.provider,
                units=snapshot.result.units,
                pit=snapshot.result.pit.value,
                quality_flags=snapshot.result.quality_flags,
                offline_stale=offline.stale,
                duckdb_rows=len(read_rows),
                crosscheck=json.loads(snapshot.result.crosscheck_json),
                partition_count=len(snapshot.partitions),
                extras=[],
            )
            kinds = [("adjustment", "raw"), ("daily", "qfq"), ("daily", "hfq")]
            if supplementary and code == "000001":
                kinds += [("financial", "raw"), ("valuation", "raw")]
            for dataset, adjustment in kinds:
                try:
                    extra = daily.model_copy(
                        update={
                            "dataset": dataset,
                            "adjustment": adjustment,
                            "adjustment_anchor": END if adjustment != "raw" else None,
                        }
                    )
                    if dataset == "financial":
                        extra = extra.model_copy(
                            update={"start": date(2024, 1, 1), "end": date(2024, 3, 31)}
                        )
                    adapter = (
                        AkShareEastmoneyAdapter(master, calendar)
                        if dataset == "valuation"
                        else BaoStockAdapter(master, calendar)
                    )
                    result = await RecordingQuantDataPort(adapter, journal).fetch(
                        extra, context(dataset + ":" + adjustment)
                    )
                    frozen = await asyncio.to_thread(store.freeze, result)
                    evidence["extras"].append(
                        {
                            "dataset": dataset,
                            "adjustment": adjustment,
                            "snapshot_id": frozen.snapshot_id,
                            "rows": frozen.row_count,
                            "pit": result.pit.value,
                            "quality_flags": result.quality_flags,
                        }
                    )
                except Exception as error:
                    evidence["extras"].append(
                        {
                            "dataset": dataset,
                            "adjustment": adjustment,
                            "error": type(error).__name__,
                            "detail": str(error),
                        }
                    )
        except Exception as error:
            evidence.update(status="ERROR", error=type(error).__name__, detail=str(error))
        (output / "summary.json").write_text(canonical(summary), encoding="utf-8")
        print(canonical(evidence), flush=True)
    engine.dispose()
    summary["finished_at"] = datetime.now(UTC).isoformat()
    (output / "summary.json").write_text(canonical(summary), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--supplementary", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.output.resolve(), args.supplementary))
