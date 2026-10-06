"""Offline, read-only acceptance audit of the Task M private snapshot bundle."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.quant.contracts import CallContext
from marketpulse.quant.data.service import FrozenDataService
from marketpulse.quant.domain import DataRightsPolicy
from marketpulse.quant.storage.models import DatasetSnapshotRow
from marketpulse.quant.storage.reader import read_snapshot
from marketpulse.quant.storage.snapshots import SnapshotStore


def deny_network(*args, **kwargs):
    raise AssertionError("offline audit attempted network/subprocess access")


async def offline(store, snapshot):
    request = snapshot.result.request.model_copy(update={"snapshot_id": snapshot.snapshot_id})
    context = CallContext(logical_key="offline:audit", ordinal=0, attempt=1, budget_seconds=1)
    return await FrozenDataService(store, ()).fetch(request, context, offline=True)


def audit(root: Path) -> dict:
    # Windows Proactor constructs a local socketpair for its own wakeup pipe.
    # Initialize that infrastructure before denying all subsequent connections.
    loop = asyncio.new_event_loop()
    socket.socket.connect = deny_network
    asyncio.create_subprocess_exec = deny_network
    engine = create_investigation_engine("sqlite:///" + (root / "metadata.sqlite").as_posix())
    store = SnapshotStore(
        create_session_factory(engine), LocalContentAddressedBlobStorage(root / "blobs")
    )
    with store.sessions() as session:
        rows = session.scalars(select(DatasetSnapshotRow)).all()
        ids = [row.snapshot_id for row in rows]
        assert all(
            "records_json" not in row.frozen_payload["result"]
            and "raw_records_json" not in row.frozen_payload["result"]
            for row in rows
        )
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "network_disabled": True,
        "metadata_contains_row_streams": False,
        "snapshots": [],
    }
    for identity in sorted(ids):
        snapshot = store.load(identity)
        view = read_snapshot(store, snapshot, snapshot.result.request.instruments[0])
        assert len(view) == snapshot.row_count
        cached = loop.run_until_complete(offline(store, snapshot))
        assert cached.stale and cached.snapshot_id == snapshot.snapshot_id
        export = DataRightsPolicy.allows(
            snapshot.result.rights, "raw_export", datetime.now(UTC), snapshot.result.request.scope
        )
        share = DataRightsPolicy.allows(
            snapshot.result.rights,
            "external_share",
            datetime.now(UTC),
            snapshot.result.request.scope,
        )
        assert not export and not share
        item = {
            "snapshot_id": identity,
            "dataset": snapshot.result.request.dataset,
            "adjustment": snapshot.result.request.adjustment,
            "rows": snapshot.row_count,
            "provider": snapshot.result.provider,
            "pit": snapshot.result.pit.value,
            "partitions": len(snapshot.partitions),
            "manifest_ref": snapshot.manifest_ref,
            "sha256_verified": True,
            "offline_stale": cached.stale,
            "raw_export_allowed": export,
            "external_share_allowed": share,
            "quality_flags": snapshot.result.quality_flags,
        }
        if item["dataset"] == "financial":
            item["financial_fields"] = sorted(view[0])
            item["bank_gross_margin_null"] = view[0]["gross_margin"] is None
            item["available_at"] = view[0]["available_at"]
            item["published_at"] = str(view[0]["published_at"])
        if item["dataset"] == "adjustment" and view:
            item["action_dates"] = [str(row["date"]) for row in view]
        report["snapshots"].append(item)
    report["snapshot_count"] = len(ids)
    report["partition_count"] = sum(item["partitions"] for item in report["snapshots"])
    engine.dispose()
    loop.run_until_complete(loop.shutdown_default_executor())
    loop.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verified {result['snapshot_count']} snapshots / {result['partition_count']} partitions")
