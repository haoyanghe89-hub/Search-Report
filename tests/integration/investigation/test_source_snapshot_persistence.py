from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError, IntegrityError

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobIntegrityError
from marketpulse.investigation.domain.enums import (
    ParseStatus,
    RunMode,
    RunStatus,
    SourceType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.domain.sources import Source, SourceSnapshot
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.services.source_snapshots import SourceSnapshotPersistence

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


def _seed(repository: InvestigationRepository) -> None:
    repository.add(
        Investigation(
            investigation_id="I-001",
            title="Snapshot test",
            event_description="A public event.",
            investigation_goal="Persist source observations.",
            scope=InvestigationScope(summary="Public sources"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="RUN-001",
            investigation_id="I-001",
            mode=RunMode.LIVE,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        Source(
            source_id="S-001",
            investigation_id="I-001",
            canonical_url="https://example.test/source",
            title="Primary source",
            source_type=SourceType.OFFICIAL_REPORT,
            is_official=True,
            is_first_hand=True,
            discovered_at=NOW,
        )
    )


def _service(repository: InvestigationRepository, blob_root: Path) -> SourceSnapshotPersistence:
    return SourceSnapshotPersistence(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(blob_root),
    )


def _persist(service: SourceSnapshotPersistence, snapshot_id: str, raw: bytes) -> SourceSnapshot:
    return service.persist(
        snapshot_id=snapshot_id,
        source_id="S-001",
        run_id="RUN-001",
        retrieved_at=NOW,
        raw_content=raw,
        cleaned_content=raw.decode().upper().encode(),
        mime_type="text/plain",
        encoding="utf-8",
        http_status=200,
        parse_status=ParseStatus.PARSED,
        parser_name="plain",
        parser_version="1",
        normalizer_version="1",
        evidence_eligible=True,
        provenance={"adapter": "fixture"},
    )


def test_snapshot_round_trip_survives_database_and_storage_reopen(
    investigation_store: tuple[InvestigationRepository, Engine, str], tmp_path: Path
) -> None:
    repository, engine, url = investigation_store
    _seed(repository)
    blob_root = tmp_path / "blobs"
    service = _service(repository, blob_root)

    first = _persist(service, "SS-001", b"first version")
    second = _persist(service, "SS-002", b"second version")
    assert first.source_id == second.source_id
    assert first.raw_blob_ref.uri.startswith("blob://sha256/")
    assert str(blob_root.resolve()) not in first.raw_blob_ref.uri

    engine.dispose()
    reopened_engine = create_investigation_engine(url)
    try:
        reopened_repository = InvestigationRepository(create_session_factory(reopened_engine))
        reopened = _service(reopened_repository, blob_root)
        loaded = reopened.load("SS-001")
        assert loaded.snapshot.snapshot_id == "SS-001"
        assert loaded.raw_content == b"first version"
        assert loaded.cleaned_content == b"FIRST VERSION"
        assert reopened_repository.get(SourceSnapshot, "SS-002").source_id == "S-001"
    finally:
        reopened_engine.dispose()


def test_database_failure_leaves_only_complete_orphan_blob(
    investigation_store: tuple[InvestigationRepository, Engine, str], tmp_path: Path
) -> None:
    repository, _, _ = investigation_store
    _seed(repository)
    blob_root = tmp_path / "blobs"
    service = _service(repository, blob_root)
    original = _persist(service, "SS-001", b"original")

    with pytest.raises(IntegrityError):
        _persist(service, "SS-001", b"orphan after duplicate row")

    loaded = service.load("SS-001")
    assert loaded.raw_content == b"original"
    assert loaded.snapshot.raw_blob_ref == original.raw_blob_ref
    orphan = LocalContentAddressedBlobStorage(blob_root).put_bytes(b"orphan after duplicate row")
    assert LocalContentAddressedBlobStorage(blob_root).verify_hash(orphan.ref)


def test_snapshot_database_row_is_immutable(
    investigation_store: tuple[InvestigationRepository, Engine, str], tmp_path: Path
) -> None:
    repository, engine, _ = investigation_store
    _seed(repository)
    _persist(_service(repository, tmp_path / "blobs"), "SS-001", b"immutable")

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE inv_source_snapshots SET parser_version='2' WHERE snapshot_id='SS-001'"
                )
            )


def test_read_revalidates_raw_and_cleaned_hashes(
    investigation_store: tuple[InvestigationRepository, Engine, str], tmp_path: Path
) -> None:
    repository, _, _ = investigation_store
    _seed(repository)
    blob_root = tmp_path / "blobs"
    service = _service(repository, blob_root)
    snapshot = _persist(service, "SS-001", b"trusted")
    raw_path = (
        blob_root
        / "sha256"
        / snapshot.raw_sha256[:2]
        / snapshot.raw_sha256[2:4]
        / snapshot.raw_sha256
    )
    raw_path.write_bytes(b"tampered")

    with pytest.raises(BlobIntegrityError):
        service.load("SS-001")
