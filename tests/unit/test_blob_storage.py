from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from marketpulse.infrastructure.storage import (
    BlobIntegrityError,
    BlobIOError,
    BlobNotFoundError,
    BlobRef,
    BlobStoragePort,
    LocalContentAddressedBlobStorage,
    local,
)


def blob_path(root: Path, ref: BlobRef) -> Path:
    return root / "sha256" / ref.sha256[:2] / ref.sha256[2:4] / ref.sha256


def test_same_content_reuses_one_physical_blob(tmp_path: Path) -> None:
    root = tmp_path / "blobs"
    store: BlobStoragePort = LocalContentAddressedBlobStorage(root)
    saved = store.put_bytes(b"source snapshot")
    assert store.put_bytes(b"source snapshot") == saved
    assert saved.ref.sha256 == hashlib.sha256(b"source snapshot").hexdigest()
    assert saved.size_bytes == len(b"source snapshot")
    assert list((root / "sha256").glob("*/*/*")) == [blob_path(root, saved.ref)]
    assert store.exists(saved.ref)
    assert store.verify_hash(saved.ref)


def test_different_content_creates_new_blob_without_changing_old(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    original = store.put_bytes(b"version 1")
    changed = store.put_bytes(b"version 2")
    assert original.ref != changed.ref
    assert store.get_bytes(original.ref) == b"version 1"
    assert store.get_bytes(changed.ref) == b"version 2"


def test_stream_and_reopened_adapter_round_trip(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    payload = "中文 evidence\n".encode() * 100_000
    source = io.BytesIO(payload)
    saved = store.put_stream(source)
    assert not source.closed
    reopened = LocalContentAddressedBlobStorage(tmp_path)
    assert reopened.get_bytes(saved.ref) == payload
    with reopened.open_stream(saved.ref) as handle:
        assert handle.read(10) == payload[:10]
        assert handle.seekable()
    assert handle.closed


def test_empty_content_is_a_valid_blob(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    saved = store.put_bytes(b"")
    assert saved.size_bytes == 0
    assert store.get_bytes(saved.ref) == b""
    assert store.verify_hash(saved.ref)


def test_reference_is_logical_round_trippable_and_immutable() -> None:
    ref = BlobRef(hashlib.sha256(b"x").hexdigest())
    assert BlobRef.from_uri(ref.uri) == ref
    assert ref.uri == f"blob://sha256/{ref.sha256}"
    with pytest.raises(FrozenInstanceError):
        ref.sha256 = "a" * 64  # type: ignore[misc]


@pytest.mark.parametrize("value", ["../escape", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_invalid_digest_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        BlobRef(value)


@pytest.mark.parametrize(
    "uri",
    ["/data/blobs/a", "file:///tmp/a", "C:\\blobs\\a", "blob://sha256/../a", "blob://md5/a"],
)
def test_non_logical_or_invalid_reference_rejected(uri: str) -> None:
    with pytest.raises(ValueError):
        BlobRef.from_uri(uri)


def test_missing_blob_fails_explicitly_without_disclosing_path(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    ref = BlobRef("0" * 64)
    assert not store.exists(ref)
    with pytest.raises(BlobNotFoundError) as error:
        store.get_bytes(ref)
    assert error.value.code == "BLOB_NOT_FOUND"
    assert str(tmp_path) not in str(error.value)
    with pytest.raises(BlobNotFoundError):
        store.verify_hash(ref)


def test_corruption_fails_before_any_bytes_are_returned(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    saved = store.put_bytes(b"correct")
    blob_path(tmp_path, saved.ref).write_bytes(b"corrupt")
    with pytest.raises(BlobIntegrityError) as error:
        store.get_bytes(saved.ref)
    assert error.value.code == "BLOB_INTEGRITY_ERROR"
    assert str(tmp_path) not in str(error.value)
    with pytest.raises(BlobIntegrityError), store.open_stream(saved.ref):
        pytest.fail("corrupt content must never reach caller")
    with pytest.raises(BlobIntegrityError):
        store.verify_hash(saved.ref)


def test_existing_corrupt_blob_is_never_overwritten(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    saved = store.put_bytes(b"immutable")
    target = blob_path(tmp_path, saved.ref)
    target.write_bytes(b"tampered")
    with pytest.raises(BlobIntegrityError):
        store.put_bytes(b"immutable")
    assert target.read_bytes() == b"tampered"
    assert not list((tmp_path / ".staging").iterdir())


class BrokenInput(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        if self.tell():
            raise OSError("simulated source stream interruption")
        return super().read(3)


def test_interrupted_input_never_publishes_partial_blob(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    with pytest.raises(BlobIOError):
        store.put_stream(BrokenInput(b"unfinished payload"))
    assert not list((tmp_path / "sha256").glob("*/*/*"))
    assert not list((tmp_path / ".staging").iterdir())


def test_publication_failure_never_returns_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError(f"simulated filesystem error {tmp_path}")

    monkeypatch.setattr(local.os, "link", fail_link)
    with pytest.raises(BlobIOError) as error:
        store.put_bytes(b"payload")
    assert str(tmp_path) not in str(error.value)
    assert not list((tmp_path / "sha256").glob("*/*/*"))
    assert not list((tmp_path / ".staging").iterdir())


def test_fsync_failure_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)

    def fail_sync(fd: int) -> None:
        raise OSError("simulated sync failure")

    monkeypatch.setattr(local.os, "fsync", fail_sync)
    with pytest.raises(BlobIOError):
        store.put_bytes(b"not durable")
    assert not list((tmp_path / "sha256").glob("*/*/*"))


def test_concurrent_duplicate_writes_reuse_blob(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    payload = b"same large snapshot" * 100_000
    with ThreadPoolExecutor(max_workers=6) as pool:
        saved = list(pool.map(store.put_bytes, [payload] * 12))
    assert all(item == saved[0] for item in saved)
    assert store.get_bytes(saved[0].ref) == payload
    assert len(list((tmp_path / "sha256").glob("*/*/*"))) == 1
    assert not list((tmp_path / ".staging").iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path spelling regression")
def test_windows_extended_path_prefix_is_not_a_false_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    candidate = tmp_path / "sha256" / "aa" / "bb"
    monkeypatch.setattr(Path, "resolve", lambda self: Path("\\\\?\\" + str(self)))
    assert store._contained(candidate) == candidate


def test_blob_reference_survives_relocation(tmp_path: Path) -> None:
    source = tmp_path / "machine-a"
    target = tmp_path / "machine-b"
    saved = LocalContentAddressedBlobStorage(source).put_bytes(b"portable")
    shutil.copytree(source, target)
    assert LocalContentAddressedBlobStorage(target).get_bytes(saved.ref) == b"portable"
    assert "machine-a" not in saved.ref.uri


def test_dangling_hash_directory_cannot_be_treated_as_blob(tmp_path: Path) -> None:
    store = LocalContentAddressedBlobStorage(tmp_path)
    ref = BlobRef("a" * 64)
    blob_path(tmp_path, ref).mkdir(parents=True)
    with pytest.raises(BlobIntegrityError):
        store.get_bytes(ref)


@pytest.mark.skipif(os.name == "nt", reason="unprivileged Windows symlink creation not assumed")
def test_symlink_cannot_escape_storage_root(tmp_path: Path) -> None:
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = LocalContentAddressedBlobStorage(root)
    (root / "sha256").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BlobIntegrityError):
        store.put_bytes(b"must stay inside")
    assert not list(outside.iterdir())


def test_process_exit_during_write_leaves_no_readable_partial_blob(tmp_path: Path) -> None:
    script = """
import io
import os
import sys
from pathlib import Path
from marketpulse.infrastructure.storage import LocalContentAddressedBlobStorage
class CrashInput(io.BytesIO):
    def read(self, size=-1):
        if self.tell():
            os._exit(77)
        return super().read(3)
LocalContentAddressedBlobStorage(Path(sys.argv[1])).put_stream(CrashInput(b'partial'))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 77, result.stderr.decode(errors="replace")
    assert not list((tmp_path / "sha256").glob("*/*/*"))
    reopened = LocalContentAddressedBlobStorage(tmp_path)
    assert not reopened.exists(BlobRef(hashlib.sha256(b"partial").hexdigest()))
    complete = reopened.put_bytes(b"partial")
    assert reopened.get_bytes(complete.ref) == b"partial"
