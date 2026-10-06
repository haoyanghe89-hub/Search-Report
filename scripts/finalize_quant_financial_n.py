"""Replay real recorded raw data with explicit parent accounting; retry missing feeds."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.quant.contracts import CallContext
from marketpulse.quant.data.akshare_adapter import AkShareEastmoneyAdapter
from marketpulse.quant.data.calendar import CalendarVerification, VerifiedCalendar
from marketpulse.quant.data.instruments import InstrumentMaster
from marketpulse.quant.data.recording import FileCallJournal, RecordingQuantDataPort
from marketpulse.quant.domain import Instrument
from marketpulse.quant.storage.models import DatasetSnapshotRow, InstrumentRow
from marketpulse.quant.storage.snapshots import SnapshotStore


class FrozenRawAdapter(AkShareEastmoneyAdapter):
    def __init__(self, master, calendar, snapshot):
        super().__init__(master, calendar)
        self.snapshot = snapshot

    async def _call(self, query, budget):
        request = self.snapshot.result.request.model_dump(mode="json")
        request["normalizer_version"] = "3-parent-2"
        if query["request"] != request:
            raise ValueError("raw replay request drift")
        return {"rows": json.loads(self.snapshot.result.raw_records_json)}


async def finalize(output, source):
    root = Path.cwd().resolve()
    output = await asyncio.to_thread(output.resolve)
    source = await asyncio.to_thread(source.resolve)
    if not source.is_relative_to(root / ".phase3-quant-n"):
        raise ValueError("private task source required")
    if not output.is_relative_to(root / ".phase3-quant-n") or output.exists():
        raise ValueError("fresh private output required")
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
            Instrument.model_validate(r.definition) for r in session.scalars(select(InstrumentRow))
        ]
        snapshots = [store.load(i) for i in session.scalars(select(DatasetSnapshotRow.snapshot_id))]
    outcomes = []
    ordinal = 0
    for instrument in instruments:
        master = InstrumentMaster((instrument,))
        native = [s for s in snapshots if instrument.instrument_id in s.result.request.instruments]
        calendar_snapshot = next(
            s
            for s in native
            if s.result.request.dataset == "calendar" and s.result.request.start == date(2022, 1, 1)
        )
        calendar_request = calendar_snapshot.result.request
        calendar = VerifiedCalendar(
            CalendarVerification(
                exchange=master.alias(instrument.instrument_id, calendar_request.start).exchange,
                start=calendar_request.start,
                end=calendar_request.end,
                sessions=tuple(
                    date.fromisoformat(r["date"])
                    for r in json.loads(calendar_snapshot.result.records_json)
                    if r["is_session"]
                ),
                source="recorded BaoStock calendar for availability",
                verified_at=calendar_snapshot.result.retrieved_at,
            )
        )
        for dataset, fields in (
            ("financial", ("balance_sheet",)),
            ("financial", ("income_statement",)),
            ("valuation", ("total_shares", "float_shares", "pe_ttm", "pb_mrq")),
        ):
            candidates = [
                s
                for s in native
                if s.result.request.dataset == dataset
                and s.result.request.fields == fields
                and s.result.request.normalizer_version == "3"
            ]
            entry = {"instrument": instrument.name, "dataset": dataset, "fields": fields}
            outcomes.append(entry)
            if not candidates:
                request = calendar_request.model_copy(
                    update={"dataset": dataset, "fields": fields, "normalizer_version": "3"}
                )
                for attempt in (1, 2):
                    ordinal += 1
                    try:
                        result = await RecordingQuantDataPort(
                            AkShareEastmoneyAdapter(master, calendar), journal
                        ).fetch(
                            request,
                            CallContext(
                                logical_key=f"retry:{instrument.instrument_id}:{fields[0]}",
                                ordinal=ordinal,
                                attempt=attempt,
                                budget_seconds=100,
                            ),
                        )
                        candidates = [await asyncio.to_thread(store.freeze, result)]
                        break
                    except Exception as error:
                        entry.setdefault("fetch_errors", []).append(str(error))
            if candidates:
                ordinal += 1
                pinned = candidates[0]
                request = pinned.result.request.model_copy(
                    update={"normalizer_version": "3-parent-2"}
                )
                result = await RecordingQuantDataPort(
                    FrozenRawAdapter(master, calendar, pinned), journal
                ).fetch(
                    request,
                    CallContext(
                        logical_key=f"normalize:{instrument.instrument_id}:{fields[0]}",
                        ordinal=ordinal,
                        attempt=1,
                        budget_seconds=30,
                    ),
                )
                provenance = json.loads(result.provenance_json)
                provenance.update(
                    raw_replay_snapshot=pinned.snapshot_id,
                    raw_retrieved_at=pinned.result.retrieved_at.isoformat(),
                    accounting_basis=(
                        "parent aggregate, total issued shares; not ordinary EPS; "
                        "preferred/perpetual distributions not deducted"
                    ),
                    financial_amount_unit="CNY_yuan",
                    shares_unit="share",
                    ttm_method="prior_annual + current_ytd - prior_comparable_ytd",
                    financial_unit_reference="https://akshare.akfamily.xyz/data/stock/stock.html",
                )
                result = result.model_copy(
                    update={
                        "provenance_json": json.dumps(
                            provenance, sort_keys=True, ensure_ascii=False
                        )
                    }
                )
                frozen = await asyncio.to_thread(store.freeze, result)
                entry.update(
                    snapshot_id=frozen.snapshot_id,
                    raw_snapshot=pinned.snapshot_id,
                    rows=frozen.row_count,
                    units=result.units,
                    flags=result.quality_flags,
                    pit=result.pit.value,
                )
            else:
                entry["missing"] = "free source unavailable after two bounded recorded attempts"
            (output / "financial-summary.json").write_text(
                json.dumps(outcomes, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(".phase3-quant-n/financial-live-03"))
    args = parser.parse_args()
    asyncio.run(finalize(args.output, args.source))
