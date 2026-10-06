"""Recorded real financial fetches into a new private bundle, never live-04 writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.quant.contracts import CallContext
from marketpulse.quant.data.akshare_adapter import AkShareEastmoneyAdapter, AkShareSinaAdapter
from marketpulse.quant.data.baostock_adapter import BaoStockAdapter
from marketpulse.quant.data.calendar import CalendarVerification, VerifiedCalendar
from marketpulse.quant.data.instruments import InstrumentMaster
from marketpulse.quant.data.recording import FileCallJournal, RecordingQuantDataPort
from marketpulse.quant.domain import DataRequest, Instrument
from marketpulse.quant.storage.models import InstrumentRow
from marketpulse.quant.storage.snapshots import SnapshotStore


async def supplement(output: Path):
    root = Path.cwd().resolve()
    output = await asyncio.to_thread(output.resolve)
    if not output.is_relative_to(root / ".phase3-quant-n") or output.exists():
        raise ValueError("fresh private output required")
    source = root / ".phase3-quant-m/live-04"
    output.mkdir(parents=True)
    with sqlite3.connect(f"file:{source / 'metadata.sqlite'}?mode=ro", uri=True) as src:
        with sqlite3.connect(output / "metadata.sqlite") as dst:
            src.backup(dst)
    shutil.copytree(source / "blobs", output / "blobs")
    engine = create_investigation_engine("sqlite:///" + (output / "metadata.sqlite").as_posix())
    sessions = create_session_factory(engine)
    store = SnapshotStore(sessions, LocalContentAddressedBlobStorage(output / "blobs"))
    journal = FileCallJournal(output / "calls")
    with sessions() as session:
        instruments = [
            Instrument.model_validate(row.definition)
            for row in session.scalars(select(InstrumentRow))
        ]
    outcomes = []
    ordinal = 0

    async def fetch(adapter, request, label):
        nonlocal ordinal
        ordinal += 1
        entry = {"instrument": request.instruments[0], "provider": adapter.provider, "label": label}
        outcomes.append(entry)
        try:
            result = await RecordingQuantDataPort(adapter, journal).fetch(
                request,
                CallContext(
                    logical_key=label + ":" + request.instruments[0],
                    ordinal=ordinal,
                    attempt=1,
                    budget_seconds=100,
                ),
            )
            snapshot = await asyncio.to_thread(store.freeze, result)
            entry.update(
                snapshot_id=snapshot.snapshot_id,
                rows=snapshot.row_count,
                flags=result.quality_flags,
                pit=result.pit.value,
            )
            return result
        except Exception as error:
            entry.update(error=type(error).__name__, detail=str(error))
            return None
        finally:
            (output / "fetch-summary.json").write_text(
                json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(entry, ensure_ascii=False), flush=True)

    for instrument in instruments:
        master = InstrumentMaster((instrument,))
        exchange = master.alias(instrument.instrument_id, date(2022, 1, 1)).exchange
        request = DataRequest(
            instruments=(instrument.instrument_id,),
            dataset="calendar",
            start=date(2022, 1, 1),
            end=date(2024, 6, 14),
            asof=datetime(2024, 6, 15, tzinfo=UTC),
        )
        placeholder = VerifiedCalendar(
            CalendarVerification(
                exchange=exchange,
                start=request.start,
                end=request.end,
                sessions=(),
                source="bootstrap_NOT_FOR_PRICE",
                verified_at=datetime.now(UTC),
            )
        )
        calendar_data = await fetch(
            BaoStockAdapter(master, placeholder), request, "calendar-financial"
        )
        if calendar_data is None:
            calendar = placeholder
        else:
            calendar = VerifiedCalendar(
                CalendarVerification(
                    exchange=exchange,
                    start=request.start,
                    end=request.end,
                    sessions=tuple(
                        date.fromisoformat(r["date"])
                        for r in json.loads(calendar_data.records_json)
                        if r["is_session"]
                    ),
                    source="recorded BaoStock financial availability calendar; not official proof",
                    verified_at=datetime.now(UTC),
                )
            )
        for label, dataset, fields, version, adapter_class in (
            ("balance", "financial", ("balance_sheet",), "3", AkShareEastmoneyAdapter),
            ("income", "financial", ("income_statement",), "3", AkShareEastmoneyAdapter),
            (
                "shares-valuation",
                "valuation",
                ("total_shares", "float_shares", "pe_ttm", "pb_mrq"),
                "3",
                AkShareEastmoneyAdapter,
            ),
            ("profit-fallback", "financial", (), "2", BaoStockAdapter),
            ("abstract-fallback", "financial", (), "2", AkShareSinaAdapter),
        ):
            item = request.model_copy(
                update={
                    "dataset": dataset,
                    "fields": fields,
                    "normalizer_version": version,
                    "start": date(2024, 5, 20) if dataset == "valuation" else request.start,
                }
            )
            await fetch(adapter_class(master, calendar), item, label)
    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(supplement(parser.parse_args().output))
