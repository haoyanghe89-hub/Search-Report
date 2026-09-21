from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.enums import ParseStatus
from marketpulse.investigation.domain.sources import SourceSnapshot
from marketpulse.investigation.persistence.repositories import InvestigationRepository


@dataclass(frozen=True, slots=True)
class PersistedSnapshot:
    snapshot: SourceSnapshot
    raw_content: bytes
    cleaned_content: bytes | None


class SourceSnapshotPersistence:
    """Coordinates immutable Blob payloads with transactional snapshot metadata."""

    def __init__(
        self,
        *,
        repository: InvestigationRepository,
        blobs: BlobStoragePort,
    ) -> None:
        self._repository = repository
        self._blobs = blobs

    def persist(
        self,
        *,
        snapshot_id: str,
        source_id: str,
        run_id: str,
        retrieved_at: datetime,
        raw_content: bytes,
        cleaned_content: bytes | None,
        mime_type: str,
        encoding: str | None,
        http_status: int | None,
        parse_status: ParseStatus,
        parser_name: str,
        parser_version: str,
        normalizer_version: str,
        evidence_eligible: bool,
        provenance: dict[str, JsonValue] | None = None,
    ) -> SourceSnapshot:
        # Payloads are finalized first. A later database rollback can only orphan a
        # complete content-addressed blob; it cannot create a dangling DB reference.
        raw = self._blobs.put_bytes(raw_content)
        self._blobs.verify_hash(raw.ref)
        cleaned = self._blobs.put_bytes(cleaned_content) if cleaned_content is not None else None
        if cleaned is not None:
            self._blobs.verify_hash(cleaned.ref)

        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source_id=source_id,
            run_id=run_id,
            retrieved_at=retrieved_at,
            raw_blob_ref=raw.ref,
            raw_sha256=raw.ref.sha256,
            cleaned_blob_ref=cleaned.ref if cleaned else None,
            cleaned_sha256=cleaned.ref.sha256 if cleaned else None,
            mime_type=mime_type,
            encoding=encoding,
            content_size=raw.size_bytes,
            http_status=http_status,
            parse_status=parse_status,
            parser_name=parser_name,
            parser_version=parser_version,
            normalizer_version=normalizer_version,
            evidence_eligible=evidence_eligible,
            provenance=provenance or {},
        )
        self._repository.add(snapshot)
        return snapshot

    def load(self, snapshot_id: str) -> PersistedSnapshot:
        snapshot = self._repository.get(SourceSnapshot, snapshot_id)
        raw = self._blobs.get_bytes(snapshot.raw_blob_ref)
        cleaned = (
            self._blobs.get_bytes(snapshot.cleaned_blob_ref)
            if snapshot.cleaned_blob_ref is not None
            else None
        )
        return PersistedSnapshot(
            snapshot=snapshot,
            raw_content=raw,
            cleaned_content=cleaned,
        )
