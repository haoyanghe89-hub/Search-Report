"""Paired database/blob archives; restores never start an investigation executor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from marketpulse.infrastructure.storage.models import BlobRef


class BackupError(ValueError):
    """Safe operational error; never includes database credentials or SQL payloads."""


class FileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = 1
    created_at: str
    dialect: str
    database: str
    files: dict[str, FileRecord]
    blob_hashes: list[str]


def _safe_path(path: Path) -> Path:
    """Reject symlink/junction ancestors, including paths outside the archive itself."""
    absolute = path.expanduser().absolute()
    for item in (absolute, *absolute.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise BackupError("Symlink or junction paths are not supported")
    return absolute.resolve()


def _new_directory(path: Path) -> Path:
    path = _safe_path(path)
    # Requiring a new path makes restore explicitly non-overwriting, even for empty dirs.
    if path.exists():
        raise BackupError("Destination must be a new, nonexistent directory")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _record(path: Path) -> FileRecord:
    path = _safe_path(path)
    if not path.is_file():
        raise BackupError("Required archive file is missing")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return FileRecord(sha256=digest.hexdigest(), size=size)


def _blob_path(digest: str) -> str:
    BlobRef(digest)
    return f"sha256/{digest[:2]}/{digest[2:4]}/{digest}"


def _references(value: Any, refs: set[str]) -> None:
    if isinstance(value, str):
        if value.startswith("blob://"):
            try:
                refs.add(BlobRef.from_uri(value).sha256)
            except ValueError:
                raise BackupError("Database contains a malformed blob reference") from None
        elif value.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except (ValueError, RecursionError):
                return
            _references(decoded, refs)
    elif isinstance(value, dict):
        for item in value.values():
            _references(item, refs)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _references(item, refs)


def _sqlite_scan(path: Path) -> set[str]:
    refs: set[str] = set()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise BackupError("SQLite foreign key check failed")
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            for row in connection.execute(f"SELECT * FROM {quoted}"):
                _references(row, refs)
    return refs


def _postgres_scan(connection: Connection) -> set[str]:
    refs: set[str] = set()
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    # Application migrations use public. Extra user schemas are included as well.
    for schema in inspector.get_schema_names():
        if schema == "information_schema" or schema.startswith("pg_"):
            continue
        for table in inspector.get_table_names(schema=schema):
            result = connection.execution_options(stream_results=True).execute(
                text(f"SELECT * FROM {quote(schema)}.{quote(table)}")
            )
            for row in result:
                _references(tuple(row), refs)
            result.close()
    return refs


def _pg_environment(url: URL) -> dict[str, str]:
    if url.get_backend_name() != "postgresql" or not url.database:
        raise BackupError("An explicit PostgreSQL database URL is required")
    environment = dict(os.environ)
    # Do not inherit another configured connection or inject secrets in process arguments.
    for key in tuple(environment):
        if key.startswith("PG"):
            del environment[key]
    for field, value in {
        "PGHOST": url.host,
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username,
        "PGPASSWORD": url.password,
        "PGDATABASE": url.database,
        "PGCONNECT_TIMEOUT": "15",
    }.items():
        if value is not None:
            environment[field] = value
    for key, option in url.query.items():
        if key not in {"sslmode", "sslrootcert", "sslcert", "sslkey", "channel_binding"}:
            raise BackupError("Unsupported PostgreSQL URL option")
        if not isinstance(option, str):
            raise BackupError("PostgreSQL URL options must be scalar")
        environment["PG" + key.upper().replace("_", "")] = option
    return environment


def _pg_command(arguments: list[str], url: URL, timeout: int) -> None:
    try:
        subprocess.run(
            arguments,
            env=_pg_environment(url),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise BackupError("PostgreSQL archive command timed out") from None
    except (subprocess.CalledProcessError, OSError):
        # pg errors can echo connection information and data. Do not expose stderr.
        raise BackupError(
            "PostgreSQL archive command failed; check tools and connectivity"
        ) from None


def _postgres_engine(url: URL) -> Any:
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        connect_args={"connect_timeout": 15},
    )


def _snapshot(url: URL, destination: Path, timeout: int) -> tuple[str, set[str]]:
    dialect = url.get_backend_name()
    if dialect == "sqlite":
        if not url.database or url.database == ":memory:" or url.query:
            raise BackupError("Backup requires a file-backed SQLite database URL")
        source = _safe_path(Path(url.database))
        if not source.is_file():
            raise BackupError("SQLite database does not exist")
        deadline = time.monotonic() + timeout

        def progress(status: int, remaining: int, total: int) -> None:
            if time.monotonic() >= deadline:
                raise BackupError("SQLite snapshot timed out")

        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as source_connection,
            closing(sqlite3.connect(destination / "database.sqlite3")) as target,
        ):
            source_connection.backup(target, pages=256, progress=progress, sleep=0.05)
        return "database.sqlite3", _sqlite_scan(destination / "database.sqlite3")
    if dialect != "postgresql":
        raise BackupError("Only SQLite and PostgreSQL are supported")
    engine = _postgres_engine(url)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text(f"SET LOCAL statement_timeout = {int(timeout * 1000)}"))
                connection.execute(text("SET TRANSACTION READ ONLY"))
                snapshot_id = str(connection.scalar(text("SELECT pg_export_snapshot()")))
                if not re.fullmatch(r"[0-9A-Fa-f-]+", snapshot_id):
                    raise BackupError("Unexpected PostgreSQL snapshot identifier")
                _pg_command(
                    [
                        "pg_dump",
                        "--format=custom",
                        "--no-owner",
                        "--no-privileges",
                        "--snapshot",
                        snapshot_id,
                        "--file",
                        str(destination / "database.dump"),
                    ],
                    url,
                    timeout,
                )
                return "database.dump", _postgres_scan(connection)
    finally:
        engine.dispose()


def _sync_tree(root: Path) -> None:
    if os.name == "nt":
        return
    for path in sorted(
        (p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True
    ):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _sync_file(path: Path) -> None:
    # Windows fsync requires a writable descriptor; this is our snapshot, never the source.
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _publish_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def backup(
    database_url: str, blob_root: Path, destination: Path, *, timeout: int = 600
) -> Manifest:
    """Snapshot DB first; copy exactly its referenced immutable blobs; publish manifest last.

    A failed/interrupted backup retains its incomplete directory for diagnosis but is
    never accepted as an archive. Source content must remain immutable (no concurrent GC).
    """
    if timeout <= 0:
        raise BackupError("Timeout must be positive")
    source_blobs = _safe_path(blob_root)
    destination = _safe_path(destination)
    if destination.is_relative_to(source_blobs) or source_blobs.is_relative_to(destination):
        raise BackupError("Archive and source blob directories must be separate")
    if (source_blobs / ".restore-quarantine.json").exists():
        raise BackupError("Restored history requires reconciliation before creating a new backup")
    if not source_blobs.is_dir():
        raise BackupError("Blob directory does not exist")
    url = make_url(database_url)
    destination = _new_directory(destination)
    # Reconciliation must include calls made during snapshot/copy, not only after publication.
    snapshot_started_at = datetime.now(UTC).isoformat()
    database, refs = _snapshot(url, destination, timeout)
    files = {database: _record(destination / database)}
    _sync_file(destination / database)
    for digest in sorted(refs):
        relative = _blob_path(digest)
        source = _safe_path(source_blobs / relative)
        source_record = _record(source)
        if source_record.sha256 != digest:
            raise BackupError("Source blob content does not match its hash")
        target = destination / "blobs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as read, target.open("xb") as write:
            shutil.copyfileobj(read, write)
            write.flush()
            os.fsync(write.fileno())
        if _record(target) != source_record:
            raise BackupError("Copied blob content failed verification")
        files["blobs/" + relative] = source_record
    manifest = Manifest(
        created_at=snapshot_started_at,
        dialect=url.get_backend_name(),
        database=database,
        files=files,
        blob_hashes=sorted(refs),
    )
    _sync_tree(destination)
    _publish_json(destination / "manifest.json", manifest.model_dump(mode="json"))
    verify(destination)
    return manifest


def verify(archive: Path) -> Manifest:
    """Check strict manifest, all archived hashes and SQLite DB/blob referential closure."""
    archive = _safe_path(archive)
    try:
        manifest = Manifest.model_validate_json(_safe_path(archive / "manifest.json").read_bytes())
    except (OSError, ValueError):
        raise BackupError("Missing or invalid archive manifest") from None
    database_names = {"sqlite": "database.sqlite3", "postgresql": "database.dump"}
    if manifest.version != 1 or database_names.get(manifest.dialect) != manifest.database:
        raise BackupError("Unsupported archive version or database format")
    if len(manifest.blob_hashes) != len(set(manifest.blob_hashes)):
        raise BackupError("Duplicate blob identities in manifest")
    try:
        expected = {manifest.database} | {
            "blobs/" + _blob_path(digest) for digest in manifest.blob_hashes
        }
    except ValueError:
        raise BackupError("Invalid blob identity in manifest") from None
    if set(manifest.files) != expected:
        raise BackupError("Unexpected or missing manifest paths")
    actual: set[str] = set()
    for path in archive.rglob("*"):
        _safe_path(path)
        if path.is_file():
            actual.add(path.relative_to(archive).as_posix())
        elif not path.is_dir():
            raise BackupError("Archive contains a non-regular object")
    if actual != expected | {"manifest.json"}:
        raise BackupError("Archive contains missing or unexpected files")
    for relative, record in manifest.files.items():
        if _record(archive / relative) != record:
            raise BackupError("Archive file content failed hash verification")
        if relative.startswith("blobs/") and record.sha256 != relative.rsplit("/", 1)[-1]:
            raise BackupError("Blob hash does not match its content identity")
    if manifest.dialect == "sqlite":
        if _sqlite_scan(archive / manifest.database) != set(manifest.blob_hashes):
            raise BackupError("Database blob references do not match the archive")
    return manifest


def restore(
    archive: Path,
    destination: Path,
    *,
    postgres_admin_url: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """Restore into a new directory and (for PG) a newly created random database.

    The admin URL selects only the server/credentials. Its database is never overwritten.
    Restore failures retain artifacts and any new database for operator investigation.
    """
    if timeout <= 0:
        raise BackupError("Timeout must be positive")
    archive = _safe_path(archive)
    manifest = verify(archive)
    destination = _safe_path(destination)
    if destination.is_relative_to(archive) or archive.is_relative_to(destination):
        raise BackupError("Restore and archive directories must be separate")
    if manifest.dialect == "postgresql" and not postgres_admin_url:
        raise BackupError("PostgreSQL restore requires an admin URL from the environment")
    destination = _new_directory(destination)
    (destination / "blobs").mkdir()
    _publish_json(
        destination / "blobs" / ".restore-quarantine.json",
        {
            "reason": "Calls after the backup snapshot may be missing; reconcile before resuming.",
            "snapshot_created_at": manifest.created_at,
        },
    )
    for relative in manifest.files:
        if not relative.startswith("blobs/"):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with (archive / relative).open("rb") as read, target.open("xb") as write:
            shutil.copyfileobj(read, write)
            write.flush()
            os.fsync(write.fileno())
        if _record(target) != manifest.files[relative]:
            raise BackupError("Restored blob verification failed")
    result: dict[str, Any] = {
        "version": 1,
        "dialect": manifest.dialect,
        "blob_count": len(manifest.blob_hashes),
        "verified_at": datetime.now(UTC).isoformat(),
        "executor_started": False,
    }
    if manifest.dialect == "sqlite":
        database_path = destination / manifest.database
        with (archive / manifest.database).open("rb") as read, database_path.open("xb") as write:
            shutil.copyfileobj(read, write)
            write.flush()
            os.fsync(write.fileno())
        if _record(database_path) != manifest.files[manifest.database]:
            raise BackupError("Restored database verification failed")
        refs = _sqlite_scan(database_path)
        result["database"] = manifest.database
        result["database_integrity_checked"] = True
    else:
        assert postgres_admin_url is not None
        admin_url = make_url(postgres_admin_url)
        _pg_environment(admin_url)
        name = "sr_restore_" + uuid.uuid4().hex
        # Write intended identity before CREATE so failure remains discoverable without secrets.
        _publish_json(destination / "restore-target.json", {"database": name})
        admin_engine = _postgres_engine(admin_url)
        try:
            with admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
        finally:
            admin_engine.dispose()
        restored_url = admin_url.set(database=name)
        _pg_command(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--single-transaction",
                "--dbname",
                name,
                str(archive / manifest.database),
            ],
            restored_url,
            timeout,
        )
        restored_engine = _postgres_engine(restored_url)
        try:
            with restored_engine.connect() as conn:
                conn.execute(text(f"SET statement_timeout = {int(timeout * 1000)}"))
                if conn.scalar(text("SELECT count(*) FROM pg_constraint WHERE NOT convalidated")):
                    raise BackupError("Restored database contains unvalidated constraints")
                refs = _postgres_scan(conn)
        finally:
            restored_engine.dispose()
        result["database"] = name
        result["database_integrity_checked"] = "restore-and-constraints"
    if refs != set(manifest.blob_hashes):
        raise BackupError("Restored database blob references do not match the archive")
    # Completion marker only after database, constraints and every blob passed validation.
    _sync_tree(destination)
    _publish_json(destination / "restore-report.json", result)
    return result


def drill(
    archive: Path,
    destination: Path,
    *,
    postgres_admin_url: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """A real isolated restore, retained for inspection. No task/network execution occurs."""
    return restore(archive, destination, postgres_admin_url=postgres_admin_url, timeout=timeout)
