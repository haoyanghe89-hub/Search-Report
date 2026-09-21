from __future__ import annotations

import re
from dataclasses import dataclass

_PREFIX = "blob://sha256/"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class BlobRef:
    """Portable content identity; never a filesystem path or arbitrary object key."""

    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("BlobRef requires a lowercase SHA-256 hex digest")

    @property
    def uri(self) -> str:
        return f"{_PREFIX}{self.sha256}"

    @classmethod
    def from_uri(cls, uri: str) -> BlobRef:
        if not uri.startswith(_PREFIX):
            raise ValueError("Expected a logical blob://sha256/ reference")
        return cls(uri[len(_PREFIX) :])


@dataclass(frozen=True, slots=True)
class StoredBlob:
    ref: BlobRef
    size_bytes: int


class BlobError(RuntimeError):
    code = "BLOB_ERROR"


class BlobNotFoundError(BlobError):
    code = "BLOB_NOT_FOUND"

    def __init__(self, ref: BlobRef) -> None:
        super().__init__(f"{self.code}: {ref.uri}")


class BlobIntegrityError(BlobError):
    code = "BLOB_INTEGRITY_ERROR"

    def __init__(self, ref: BlobRef | None = None) -> None:
        super().__init__(f"{self.code}: {ref.uri if ref else 'unsafe storage object'}")


class BlobIOError(BlobError):
    code = "BLOB_IO_ERROR"

    def __init__(self) -> None:
        # Filesystem exception strings can disclose machine-specific paths.
        super().__init__(f"{self.code}: storage operation could not be completed")
