import tempfile
from pathlib import Path

from marketpulse.infrastructure.storage.models import BlobRef

from ..domain import DatasetSnapshot
from .snapshots import SnapshotStore


def read_snapshot(
    store: SnapshotStore, snapshot: DatasetSnapshot, instrument_id: str, limit: int = 5000
) -> list[dict]:
    """One independent read-only DuckDB catalog per invocation; bounded fixed query."""
    import duckdb

    if not 1 <= limit <= 5000 or instrument_id not in snapshot.result.request.instruments:
        raise ValueError("reader bounds/identity mismatch")
    verified = store.load(snapshot.snapshot_id)
    with tempfile.TemporaryDirectory(prefix="quant-reader-") as directory:
        catalog = str(Path(directory) / "catalog.duckdb")
        duckdb.connect(catalog).close()
        paths = []
        for ordinal, part in enumerate(verified.partitions):
            if part.layer == "normalized":
                path = Path(directory) / f"part-{ordinal}.parquet"
                path.write_bytes(store.blobs.get_bytes(BlobRef.from_uri(part.blob_ref)))
                paths.append(str(path))
        with duckdb.connect(
            catalog,
            read_only=True,
            config={
                "memory_limit": "128MB",
                "threads": "1",
                "enable_external_access": "true",
                "autoinstall_known_extensions": "false",
                "autoload_known_extensions": "false",
            },
        ) as connection:
            response = connection.execute(
                "SELECT * EXCLUDE (_quant_ordinal, _quant_json) "
                "FROM read_parquet(?, union_by_name=true) "
                "WHERE instrument_id = ? ORDER BY _quant_ordinal LIMIT ?",
                [paths, instrument_id, limit],
            )
            columns = [column[0] for column in response.description]
            return [dict(zip(columns, row, strict=True)) for row in response.fetchall()]
