from __future__ import annotations

from contextlib import AbstractContextManager
from typing import BinaryIO, Protocol

from marketpulse.infrastructure.storage.models import BlobRef, StoredBlob


class BlobStoragePort(Protocol):
    """Immutable storage. Async consumers should offload blocking I/O from the event loop.

    Reads verify content before exposing bytes. Missing/corrupt objects raise explicit
    Blob errors; exists checks presence only. No operation accepts an OS path as a ref.
    """

    def put_bytes(self, content: bytes) -> StoredBlob: ...

    def put_stream(self, stream: BinaryIO) -> StoredBlob: ...

    def get_bytes(self, ref: BlobRef) -> bytes: ...

    def open_stream(self, ref: BlobRef) -> AbstractContextManager[BinaryIO]: ...

    def exists(self, ref: BlobRef) -> bool: ...

    def verify_hash(self, ref: BlobRef) -> bool: ...
