import json
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobIntegrityError, BlobRef
from marketpulse.investigation.deletion import delete_archive
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import InvestigationRow
from marketpulse.quant.contracts import CallContext
from marketpulse.quant.data.base import ProviderUnavailable
from marketpulse.quant.data.recording import MemoryCallJournal, RecordingQuantDataPort
from marketpulse.quant.data.service import FrozenDataService
from marketpulse.quant.storage.reader import read_snapshot
from marketpulse.quant.storage.snapshots import SnapshotStore
from tests.unit.quant.test_contracts_data import ID, instrument, request, result


@pytest.fixture
def store(tmp_path):
    url = "sqlite:///" + (tmp_path / "quant.db").as_posix()
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_investigation_engine(url)
    value = SnapshotStore(
        create_session_factory(engine), LocalContentAddressedBlobStorage(tmp_path / "blobs")
    )
    value.register(instrument())
    yield value
    engine.dispose()


def test_frozen_manifest_and_partition_hashes(store):
    snapshot = store.freeze(result())
    assert len(snapshot.partitions) == 2 and snapshot.row_count == 1
    assert store.freeze(result()).snapshot_id == snapshot.snapshot_id
    assert store.load(snapshot.snapshot_id) == snapshot
    assert read_snapshot(store, snapshot, ID)[0]["close"] == 10
    assert store.find(request(), stale=True).stale
    with store.sessions() as session:
        assert {
            "inv_quant_instrument",
            "inv_quant_dataset_snapshot",
            "inv_quant_snapshot_ownership",
        } <= set(inspect(session.bind).get_table_names())
    with pytest.raises(IntegrityError), store.sessions.begin() as session:
        session.execute(text("UPDATE inv_quant_dataset_snapshot SET row_count=9"))


def test_no_latest_and_manifest_corruption(store):
    first = store.freeze(result())
    store.freeze(result(close=12))
    with pytest.raises(ValueError):
        store.find(request())
    assert store.find(request(snapshot_id=first.snapshot_id)).snapshot_id == first.snapshot_id
    with pytest.raises(ValueError):
        store.find(request(snapshot_id=first.snapshot_id, fields=("close",)))


def test_parquet_multi_year_metadata_only_and_offline_integrity(store):
    from marketpulse.quant.contracts import canonical

    value = result(req=request(start=date(2023, 1, 1)))
    rows = json.loads(value.records_json)
    rows.insert(0, {**rows[0], "date": "2023-12-29"})
    value = value.model_copy(
        update={"records_json": canonical(rows), "raw_records_json": canonical(rows)}
    )
    snapshot = store.freeze(value)
    assert len(snapshot.partitions) == 4
    with store.sessions() as session:
        payload = session.execute(
            text("SELECT frozen_payload FROM inv_quant_dataset_snapshot")
        ).scalar_one()
        assert '"records_json"' not in payload and '"raw_records_json"' not in payload
    assert store.load(snapshot.snapshot_id).result.records_json == value.records_json
    ref = BlobRef.from_uri(snapshot.partitions[0].blob_ref)
    store.blobs._path(ref).write_bytes(b"broken")  # corrupt one test-owned exact digest
    with pytest.raises(BlobIntegrityError):
        store.find(value.request, stale=True)


def test_shared_ownership_archive_delete_preserves_snapshot(store):
    snapshot = store.freeze(result())
    now = datetime.now(UTC)
    with store.sessions.begin() as session:
        for name in ("archive_a", "archive_b"):
            session.add(
                InvestigationRow(
                    investigation_id=name,
                    title=name,
                    event_description="T",
                    investigation_goal="T",
                    scope={},
                    created_at=now,
                    updated_at=now,
                )
            )
    for name in ("archive_a", "archive_b"):
        store.attach(snapshot.snapshot_id, name)
    deleted = delete_archive(store.sessions, "archive_a", store.blobs)
    assert deleted["deleted_records"]["inv_quant_snapshot_ownership"] == 1
    assert "inv_quant_dataset_snapshot" not in deleted["deleted_records"]
    assert store.load(snapshot.snapshot_id).row_count == 1
    with store.sessions() as session:
        assert (
            session.execute(text("SELECT count(*) FROM inv_quant_snapshot_ownership")).scalar_one()
            == 1
        )


def test_complete_sessions_freeze_rejects_provisional(store):
    from marketpulse.quant.contracts import canonical

    value = result()
    rows = json.loads(value.records_json)
    rows[0]["provisional"] = True
    with pytest.raises(ValueError):
        store.freeze(value.model_copy(update={"records_json": canonical(rows)}))


def test_verified_empty_actions_are_not_missing_data(store):
    value = result(req=request(dataset="adjustment")).model_copy(
        update={
            "records_json": "[]",
            "raw_records_json": "[]",
            "quality_flags": ("no_actions_in_range",),
        }
    )
    snapshot = store.freeze(value)
    assert snapshot.row_count == 0 and len(snapshot.partitions) == 2
    assert store.load(snapshot.snapshot_id).result.records_json == "[]"
    assert read_snapshot(store, snapshot, ID) == []


@pytest.mark.asyncio
async def test_offline_and_recorded_fallback(store):
    class Adapter:
        upstream = "fixture"

        def __init__(self, provider, fail=False, close=10):
            self.provider, self.fail, self.close = provider, fail, close

        async def fetch(self, req, context):
            if self.fail:
                raise ProviderUnavailable("fixture timeout")
            return result(provider=self.provider, req=req, close=self.close)

    journal = MemoryCallJournal()
    ports = tuple(
        RecordingQuantDataPort(a, journal)
        for a in (
            Adapter("baostock", fail=True),
            Adapter("akshare_tencent"),
            Adapter("akshare_eastmoney", close=12),
        )
    )
    service = FrozenDataService(store, ports)
    context = CallContext(logical_key="fallback", ordinal=0, attempt=1, budget_seconds=5)
    value = await service.fetch(request(), context)
    assert value.result.provider == "akshare_tencent"
    assert "crosscheck_conflict_claims_paused" in value.result.quality_flags
    assert len(journal.calls) == 3
    assert json.loads(value.result.records_json)[0]["close"] == 10
    assert (await service.fetch(request(), context, offline=True)).stale
    assert len(journal.calls) == 3
