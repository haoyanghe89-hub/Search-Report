from __future__ import annotations

import hashlib
from collections.abc import Mapping

from marketpulse.infrastructure.storage.models import BlobIntegrityError, BlobNotFoundError
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.enums import ArtifactType
from marketpulse.investigation.domain.locators import PdfTextRangeLocator, TextRangeLocator
from marketpulse.investigation.domain.sources import DocumentArtifact, Evidence, SourceSnapshot
from marketpulse.investigation.ingestion.locators import LocatorResolutionError, resolve_locator
from marketpulse.investigation.validation.models import (
    EvidenceIntegrityResult,
    IntegrityErrorCode,
    IntegrityFailure,
    RecognizedArtifactVersions,
)


class EvidenceIntegrityValidator:
    """Validates immutable Evidence without depending on Agents or Harness execution."""

    def __init__(
        self,
        *,
        blobs: BlobStoragePort,
        recognized_versions: RecognizedArtifactVersions,
    ) -> None:
        self._blobs = blobs
        self._recognized_versions = recognized_versions

    def validate_reference(
        self,
        *,
        evidence_id: str,
        evidence_by_id: Mapping[str, Evidence],
        snapshot_by_id: Mapping[str, SourceSnapshot],
        artifact_by_id: Mapping[str, DocumentArtifact],
    ) -> EvidenceIntegrityResult:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            return self._invalid(
                evidence_id,
                IntegrityFailure(
                    code=IntegrityErrorCode.MISSING_EVIDENCE,
                    detail="referenced Evidence does not exist",
                ),
            )
        return self.validate(
            evidence=evidence,
            snapshot=snapshot_by_id.get(evidence.snapshot_id),
            artifact=(
                artifact_by_id.get(evidence.artifact_id)
                if evidence.artifact_id is not None
                else None
            ),
        )

    def validate(
        self,
        *,
        evidence: Evidence,
        snapshot: SourceSnapshot | None,
        artifact: DocumentArtifact | None,
    ) -> EvidenceIntegrityResult:
        failures: list[IntegrityFailure] = []
        if snapshot is None:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.MISSING_SNAPSHOT,
                    detail="Evidence Snapshot does not exist",
                )
            )
        if artifact is None:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.MISSING_ARTIFACT,
                    detail="Evidence DocumentArtifact does not exist",
                )
            )
        if snapshot is not None and not self._snapshot_version_is_recognized(snapshot):
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.UNRECOGNIZED_VERSION,
                    detail="Snapshot parser or normalizer version is not recognized",
                )
            )
        if artifact is not None and not self._artifact_version_is_recognized(artifact):
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.UNRECOGNIZED_VERSION,
                    detail="Artifact processor version is not recognized",
                )
            )
        if artifact is not None and artifact.snapshot_id != evidence.snapshot_id:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.SNAPSHOT_ARTIFACT_MISMATCH,
                    detail="Evidence and Artifact reference different Snapshots",
                )
            )
        if failures:
            return EvidenceIntegrityResult(
                evidence_id=evidence.evidence_id,
                valid=False,
                snapshot_id=evidence.snapshot_id,
                artifact_id=evidence.artifact_id,
                failures=tuple(failures),
            )
        assert artifact is not None

        artifact_content = self._load_blob(artifact, failures)
        if artifact_content is None:
            return EvidenceIntegrityResult(
                evidence_id=evidence.evidence_id,
                valid=False,
                snapshot_id=evidence.snapshot_id,
                artifact_id=evidence.artifact_id,
                failures=tuple(failures),
            )

        locator_failure = self._validate_locator_shape(evidence, artifact, artifact_content)
        if locator_failure is not None:
            failures.append(locator_failure)
            return EvidenceIntegrityResult(
                evidence_id=evidence.evidence_id,
                valid=False,
                snapshot_id=evidence.snapshot_id,
                artifact_id=evidence.artifact_id,
                failures=tuple(failures),
            )

        try:
            excerpt = resolve_locator(
                evidence.locator,
                artifact_content,
                page_number=artifact.page_number,
            )
        except LocatorResolutionError as error:
            code = (
                IntegrityErrorCode.LOCATOR_OUT_OF_RANGE
                if "exceeds" in str(error)
                else IntegrityErrorCode.QUOTE_MISMATCH
                if "quote hash" in str(error)
                else IntegrityErrorCode.INVALID_LOCATOR
            )
            failures.append(IntegrityFailure(code=code, detail=str(error)))
            return EvidenceIntegrityResult(
                evidence_id=evidence.evidence_id,
                valid=False,
                snapshot_id=evidence.snapshot_id,
                artifact_id=evidence.artifact_id,
                failures=tuple(failures),
            )

        content_hash = hashlib.sha256(evidence.content.encode("utf-8")).hexdigest()
        if excerpt != evidence.content or content_hash != evidence.content_hash:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.QUOTE_MISMATCH,
                    detail="resolved Artifact excerpt does not match persisted Evidence content",
                )
            )
        if hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != evidence.locator.quote_hash:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.QUOTE_MISMATCH,
                    detail="resolved excerpt hash does not match locator quote hash",
                )
            )
        if failures:
            return EvidenceIntegrityResult(
                evidence_id=evidence.evidence_id,
                valid=False,
                snapshot_id=evidence.snapshot_id,
                artifact_id=evidence.artifact_id,
                failures=tuple(failures),
            )
        return EvidenceIntegrityResult(
            evidence_id=evidence.evidence_id,
            valid=True,
            snapshot_id=evidence.snapshot_id,
            artifact_id=evidence.artifact_id,
            resolved_excerpt=excerpt,
        )

    def _load_blob(
        self,
        artifact: DocumentArtifact,
        failures: list[IntegrityFailure],
    ) -> bytes | None:
        try:
            if not self._blobs.exists(artifact.blob_ref):
                failures.append(
                    IntegrityFailure(
                        code=IntegrityErrorCode.BLOB_NOT_FOUND,
                        detail="Artifact Blob does not exist",
                    )
                )
                return None
            if not self._blobs.verify_hash(artifact.blob_ref):
                failures.append(
                    IntegrityFailure(
                        code=IntegrityErrorCode.BLOB_INTEGRITY_ERROR,
                        detail="Artifact Blob hash verification failed",
                    )
                )
                return None
            content = self._blobs.get_bytes(artifact.blob_ref)
        except BlobNotFoundError:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.BLOB_NOT_FOUND,
                    detail="Artifact Blob does not exist",
                )
            )
            return None
        except BlobIntegrityError:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.BLOB_INTEGRITY_ERROR,
                    detail="Artifact Blob hash verification failed",
                )
            )
            return None
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            failures.append(
                IntegrityFailure(
                    code=IntegrityErrorCode.BLOB_INTEGRITY_ERROR,
                    detail="Artifact content does not match persisted hash",
                )
            )
            return None
        return content

    @staticmethod
    def _validate_locator_shape(
        evidence: Evidence,
        artifact: DocumentArtifact,
        artifact_content: bytes,
    ) -> IntegrityFailure | None:
        locator = evidence.locator
        if isinstance(locator, PdfTextRangeLocator):
            if artifact.artifact_type is not ArtifactType.PDF_PAGE_TEXT:
                return IntegrityFailure(
                    code=IntegrityErrorCode.INVALID_LOCATOR,
                    detail="PDF locator requires a PDF page Artifact",
                )
            if artifact.page_number != locator.page:
                return IntegrityFailure(
                    code=IntegrityErrorCode.INVALID_LOCATOR,
                    detail="PDF locator page does not match Artifact page",
                )
        elif not isinstance(locator, TextRangeLocator):
            return IntegrityFailure(
                code=IntegrityErrorCode.INVALID_LOCATOR,
                detail="unsupported locator type",
            )
        try:
            length = len(artifact_content.decode("utf-8"))
        except UnicodeDecodeError:
            return IntegrityFailure(
                code=IntegrityErrorCode.INVALID_LOCATOR,
                detail="Artifact is not normalized UTF-8 text",
            )
        if locator.start < 0 or locator.end <= locator.start or locator.end > length:
            return IntegrityFailure(
                code=IntegrityErrorCode.LOCATOR_OUT_OF_RANGE,
                detail="locator range is outside Artifact text",
            )
        return None

    def _snapshot_version_is_recognized(self, snapshot: SourceSnapshot) -> bool:
        return (
            snapshot.parser_name,
            snapshot.parser_version,
            snapshot.normalizer_version,
        ) in self._recognized_versions.snapshot_parsers

    def _artifact_version_is_recognized(self, artifact: DocumentArtifact) -> bool:
        return (
            artifact.processor_name,
            artifact.processor_version,
        ) in self._recognized_versions.artifact_processors

    @staticmethod
    def _invalid(evidence_id: str, *failures: IntegrityFailure) -> EvidenceIntegrityResult:
        return EvidenceIntegrityResult(
            evidence_id=evidence_id,
            valid=False,
            failures=failures,
        )
