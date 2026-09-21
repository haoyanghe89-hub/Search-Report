from __future__ import annotations

import hashlib
import io
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO, BinaryIO

from marketpulse.infrastructure.storage.models import (
    BlobIntegrityError,
    BlobIOError,
    BlobNotFoundError,
    BlobRef,
    StoredBlob,
)

_CHUNK_SIZE = 1024 * 1024


def _resolved(path: Path) -> Path:
    value = str(path.resolve())
    # On Windows a concurrent mkdir can make realpath retain the extended prefix.
    # Normalize equivalent DOS/UNC spellings before checking containment.
    if os.name == "nt" and value.startswith("\\\\?\\"):
        value = "\\\\" + value[8:] if value[4:8].upper() == "UNC\\" else value[4:]
    return Path(value)


def _digest(stream: IO[bytes]) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        # Windows has no portable directory fsync. File bytes are still fsynced.
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LocalContentAddressedBlobStorage:
    """Local immutable SHA-256 store, using same-volume atomic no-clobber publication.

    The configured volume is trusted. Hard links must be supported (NTFS/local Linux
    volumes); there is intentionally no non-atomic fallback. A killed process may
    leave an unreferenced staging file or complete orphan, never a partial final key.
    """

    def __init__(self, root: Path) -> None:
        try:
            self._root = _resolved(root.expanduser())
            self._root.mkdir(parents=True, exist_ok=True)
            self._staging = self._contained(self._root / ".staging")
            self._staging.mkdir(exist_ok=True)
            _sync_directory(self._root)
            _sync_directory(self._root.parent)
        except OSError:
            raise BlobIOError() from None

    def _contained(self, path: Path) -> Path:
        if path.is_symlink() or not _resolved(path).is_relative_to(self._root):
            raise BlobIntegrityError()
        return path

    def _path(self, ref: BlobRef) -> Path:
        digest = ref.sha256
        return self._contained(self._root / "sha256" / digest[:2] / digest[2:4] / digest)

    def put_bytes(self, content: bytes) -> StoredBlob:
        return self.put_stream(io.BytesIO(content))

    def put_stream(self, stream: BinaryIO) -> StoredBlob:
        temporary: Path | None = None
        try:
            # Recheck the staging boundary if the directory changed since construction.
            self._contained(self._staging)
            with tempfile.NamedTemporaryFile(
                mode="w+b", dir=self._staging, prefix="blob-", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                digest = hashlib.sha256()
                size = 0
                while chunk := stream.read(_CHUNK_SIZE):
                    digest.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
                ref = BlobRef(digest.hexdigest())
                handle.seek(0)
                if _digest(handle.file) != (ref.sha256, size):
                    raise BlobIntegrityError(ref)

            target = self._path(ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._contained(target)
            try:
                # Unlike os.replace, link cannot overwrite a concurrently published blob.
                os.link(temporary, target)
            except FileExistsError:
                self.verify_hash(ref)
            directory = target.parent
            while True:
                _sync_directory(directory)
                if directory == self._root:
                    break
                directory = directory.parent
            return StoredBlob(ref=ref, size_bytes=size)
        except OSError:
            raise BlobIOError() from None
        finally:
            if temporary is not None:
                # Cleanup failure can leave an orphan, but must never damage final blobs.
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)

    def _open_verified(self, ref: BlobRef) -> BinaryIO:
        handle: BinaryIO | None = None
        try:
            path = self._path(ref)
            if not stat.S_ISREG(path.stat().st_mode):
                raise BlobIntegrityError(ref)
            handle = path.open("rb")
            if _digest(handle)[0] != ref.sha256:
                raise BlobIntegrityError(ref)
            handle.seek(0)
            return handle
        except BaseException as error:
            if handle is not None:
                handle.close()
            if isinstance(error, FileNotFoundError):
                raise BlobNotFoundError(ref) from None
            if isinstance(error, OSError):
                raise BlobIOError() from None
            raise

    @contextmanager
    def open_stream(self, ref: BlobRef) -> Iterator[BinaryIO]:
        handle = self._open_verified(ref)
        try:
            yield handle
        finally:
            handle.close()

    def get_bytes(self, ref: BlobRef) -> bytes:
        try:
            with self.open_stream(ref) as handle:
                return handle.read()
        except OSError:
            raise BlobIOError() from None

    def exists(self, ref: BlobRef) -> bool:
        try:
            path = self._path(ref)
            if not stat.S_ISREG(path.stat().st_mode):
                raise BlobIntegrityError(ref)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            raise BlobIOError() from None

    def verify_hash(self, ref: BlobRef) -> bool:
        with self.open_stream(ref):
            return True
