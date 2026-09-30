from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import make_url

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.enums import AuditActorType, RunMode, RunStatus, WorkflowPhase
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
    RunBudget,
)
from marketpulse.investigation.harness.checkpoints import StepInputCheckpoints, WorkerCheckpoint
from marketpulse.investigation.operations import backup as operations
from marketpulse.investigation.operations.backup import BackupError, backup, drill, restore, verify
from marketpulse.investigation.persistence.repositories import InvestigationRepository


@pytest.fixture
def paired_source(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> tuple[str, Path, InvestigationRepository]:
    repository, _, url = investigation_store
    now = datetime.now(UTC)
    repository.add(
        Investigation(
            investigation_id="I-backup",
            title="Archive drill",
            event_description="offline",
            investigation_goal="recover",
            scope=InvestigationScope(summary="test"),
            created_at=now,
            updated_at=now,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="R-backup",
            investigation_id="I-backup",
            mode=RunMode.LIVE,
            status=RunStatus.INTERRUPTED,
            current_phase=WorkflowPhase.PLAN,
            checkpoint_version=3,
            state_version=8,
            workflow_version="resumable-retrieval-v4",
            created_at=now,
            updated_at=now,
        )
    )
    repository.add(
        RunBudget(
            run_id="R-backup",
            max_research_rounds=4,
            max_search_calls=20,
            max_fetch_calls=20,
            max_model_calls=12,
            max_tokens=10000,
            max_wall_time_ms=100000,
            model_calls_used=3,
            tokens_used=145,
            consumed_wall_time_ms=41,
            updated_at=now,
        )
    )
    blobs = LocalContentAddressedBlobStorage(tmp_path / "source-blobs")
    StepInputCheckpoints(repository, blobs).pinned_input(
        "R-backup",
        "validation:workers",
        "resumable-retrieval-v4",
        WorkerCheckpoint(workers=2),
    )
    request = blobs.put_bytes(b'{"request":"already dispatched"}')
    repository.add(
        AuditEvent(
            audit_event_id="intent",
            investigation_id="I-backup",
            run_id="R-backup",
            actor_type=AuditActorType.SYSTEM,
            event_type="MODEL_CALL_INTENT",
            target_type="ModelCall",
            target_id="unknown-call",
            metadata={"request_ref": request.ref.uri, "status": "UNKNOWN"},
            created_at=now,
        )
    )
    blobs.put_bytes(b"unreferenced incomplete work is unnecessary to restore snapshot")
    return url, tmp_path / "source-blobs", repository


def test_real_sqlite_drill_preserves_checkpoints_intents_and_budget(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
) -> None:
    url, blobs, repository = paired_source
    archive = tmp_path / "archive"
    manifest = backup(url, blobs, archive)
    assert len(manifest.blob_hashes) == 2
    original = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
    output = tmp_path / "drill"
    report = drill(archive, output)
    assert report["executor_started"] is False
    assert report["database_integrity_checked"] is True
    with sqlite3.connect(output / "database.sqlite3") as connection:
        assert connection.execute(
            "SELECT state_version, checkpoint_version, status FROM inv_runs"
        ).fetchone() == (8, 3, "INTERRUPTED")
        assert connection.execute(
            "SELECT model_calls_used, tokens_used, consumed_wall_time_ms FROM inv_run_budgets"
        ).fetchone() == (3, 145, 41)
        assert set(connection.execute("SELECT event_type FROM inv_audit_events")) == {
            ("STEP_INPUT_SAVED",),
            ("MODEL_CALL_INTENT",),
        }
    assert repository.get(RunBudget, "R-backup").model_calls_used == 3
    assert original == {
        p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()
    }
    assert verify(archive) == manifest


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_source_missing_or_corrupt_blob_never_publishes_manifest(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
    damage: str,
) -> None:
    url, blobs, _ = paired_source
    target = next(p for p in blobs.rglob("*") if p.is_file() and b"workers" in p.read_bytes())
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"bad content")
    destination = tmp_path / "failed-archive"
    with pytest.raises(BackupError):
        backup(url, blobs, destination)
    assert not (destination / "manifest.json").exists()


@pytest.mark.parametrize("damage", ["database", "blob", "traversal", "omitted", "extra"])
def test_archive_corruption_and_incomplete_reference_closure_fail_closed(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
    damage: str,
) -> None:
    url, blobs, _ = paired_source
    archive = tmp_path / "archive"
    backup(url, blobs, archive)
    manifest_path = archive / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    blob_key = next(key for key in manifest["files"] if key.startswith("blobs/"))
    if damage == "database":
        (archive / "database.sqlite3").write_bytes(b"invalid")
    elif damage == "blob":
        (archive / blob_key).write_bytes(b"corrupted")
    elif damage == "traversal":
        manifest["files"]["../escaped"] = manifest["files"].pop(blob_key)
    elif damage == "omitted":
        del manifest["files"][blob_key]
        manifest["blob_hashes"].remove(blob_key.rsplit("/", 1)[1])
        (archive / blob_key).unlink()
    else:
        (archive / "unlisted.txt").write_text("unexpected")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BackupError):
        verify(archive)
    with pytest.raises(BackupError):
        restore(archive, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()


def test_restore_refuses_existing_destination_and_preserves_archive(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
) -> None:
    url, blobs, _ = paired_source
    archive = tmp_path / "archive"
    backup(url, blobs, archive)
    destination = tmp_path / "occupied"
    destination.mkdir()
    sentinel = destination / "live.sqlite3"
    sentinel.write_bytes(b"never overwrite")
    with pytest.raises(BackupError, match="nonexistent"):
        restore(archive, destination)
    assert sentinel.read_bytes() == b"never overwrite"
    with pytest.raises(BackupError, match="separate"):
        restore(archive, archive / "restore")
    verify(archive)


def test_snapshot_precedes_blob_copy_and_excludes_later_database_writes(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url, blobs, _ = paired_source
    snapshot = operations._snapshot
    snapshot_times = []

    def change_after_snapshot(*args: Any, **kwargs: Any) -> Any:
        result = snapshot(*args, **kwargs)
        snapshot_times.append(datetime.now(UTC))
        with sqlite3.connect(make_url(url).database) as connection:
            connection.execute("UPDATE inv_run_budgets SET model_calls_used=4")
        return result

    monkeypatch.setattr(operations, "_snapshot", change_after_snapshot)
    archive = tmp_path / "archive"
    manifest = backup(url, blobs, archive)
    assert datetime.fromisoformat(manifest.created_at) <= snapshot_times[0]
    output = tmp_path / "restore"
    drill(archive, output)
    with sqlite3.connect(output / "database.sqlite3") as connection:
        assert connection.execute("SELECT model_calls_used FROM inv_run_budgets").fetchone() == (3,)


def test_symlink_archive_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is not available for this Windows user")
    with pytest.raises(BackupError, match="Symlink"):
        verify(link)


def test_postgres_subprocess_hides_secrets_and_has_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def run(arguments: list[str], **kwargs: Any) -> None:
        calls.append({"arguments": arguments, **kwargs})
        raise subprocess.TimeoutExpired(arguments, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    url = make_url("postgresql://backup:secret-never-log@localhost/archive")
    with pytest.raises(BackupError, match="timed out") as error:
        operations._pg_command(["pg_dump", "--format=custom"], url, 7)
    assert "secret" not in str(error.value)
    assert "secret" not in repr(calls[0]["arguments"])
    assert calls[0]["env"]["PGPASSWORD"] == "secret-never-log"
    assert calls[0]["timeout"] == 7


def test_cli_drill_is_offline_and_does_not_expose_database_url(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
) -> None:
    import sys

    url, blobs, _ = paired_source
    archive = tmp_path / "archive"
    environment = dict(os.environ, PAIRED_BACKUP_TEST_DB=url)
    prefix = [sys.executable, "-m", "marketpulse.investigation.operations.backup_cli"]
    created = subprocess.run(
        [
            *prefix,
            "backup",
            "--database-url-env",
            "PAIRED_BACKUP_TEST_DB",
            "--blob-root",
            str(blobs),
            "--destination",
            str(archive),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(created.stdout)["verified"] is True
    result = subprocess.run(
        [*prefix, "drill", "--archive", str(archive), "--destination", str(tmp_path / "drill")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(result.stdout)["executor_started"] is False
    assert url not in created.stdout + created.stderr + result.stdout + result.stderr


def test_restore_marks_quarantine_and_cannot_silently_rebackup(
    paired_source: tuple[str, Path, InvestigationRepository],
    tmp_path: Path,
) -> None:
    url, blobs, _ = paired_source
    archive = tmp_path / "archive"
    backup(url, blobs, archive)
    target = tmp_path / "drill"
    drill(archive, target)
    assert (target / "blobs" / ".restore-quarantine.json").is_file()
    with pytest.raises(BackupError, match="reconciliation"):
        backup(
            f"sqlite:///{(target / 'database.sqlite3').as_posix()}",
            target / "blobs",
            tmp_path / "washed",
        )
