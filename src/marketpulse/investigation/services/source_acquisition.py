from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.claims import ResearchGap
from marketpulse.investigation.domain.enums import (
    GapSeverity,
    GapStatus,
    ParseStatus,
    ResearchGapType,
    SourceType,
)
from marketpulse.investigation.domain.sources import DocumentArtifact, Source, SourceSnapshot
from marketpulse.investigation.ingestion.models import DocumentParseRequest
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.repositories import (
    InvestigationRepository,
    PersistedEntity,
)
from marketpulse.investigation.ports.external import (
    FetchPort,
    FetchRequest,
    SearchPort,
    SearchRequest,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


def _now() -> datetime:
    return datetime.now(UTC)


def _id(kind: str) -> str:
    return f"{kind.upper()}-{uuid.uuid4().hex}"


class AcquisitionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AcquisitionRequest(AcquisitionModel):
    investigation_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)
    search_schema_version: str = "1"
    fetch_schema_version: str = "1"
    config_version: str = "runtime-v1"


class AcquiredSource(AcquisitionModel):
    source_id: str
    snapshot_id: str | None = None
    discovered: bool
    fetched: bool
    parsed: bool
    evidence_eligible: bool
    valid_for_statistics: bool
    parse_status: ParseStatus | None = None
    artifact_ids: tuple[str, ...] = ()
    gap_ids: tuple[str, ...] = ()


class AcquisitionResult(AcquisitionModel):
    query: str
    sources: tuple[AcquiredSource, ...]

    @property
    def valid_source_count(self) -> int:
        return sum(source.valid_for_statistics for source in self.sources)


_SOURCE_TYPES = {
    "official": SourceType.OFFICIAL_REPORT,
    "research": SourceType.TECHNICAL_ANALYSIS,
    "media": SourceType.NEWS,
}


@dataclass(frozen=True, slots=True)
class PreparedAcquisition:
    result: AcquisitionResult
    business_outputs: tuple[PersistedEntity, ...]


def _stable_id(kind: str, *parts: str) -> str:
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{kind.upper()}-{digest}"


def _stable_factory(run_id: str, logical_step_key: str, canonical_url: str) -> IdFactory:
    counters: dict[str, int] = {}

    def factory(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return _stable_id(kind, run_id, logical_step_key, canonical_url, str(counters[kind]))

    return factory


class SourceAcquisitionService:
    """Deterministic Search-to-artifact pipeline with no Claim or report semantics."""

    def __init__(
        self,
        *,
        repository: InvestigationRepository,
        blobs: BlobStoragePort,
        search: SearchPort,
        fetch: FetchPort,
        parsers: DocumentParserRegistry,
        id_factory: IdFactory = _id,
        clock: Clock = _now,
    ) -> None:
        self._repository = repository
        self._blobs = blobs
        self._search = search
        self._fetch = fetch
        self._parsers = parsers
        self._id_factory = id_factory
        self._clock = clock

    async def acquire(self, request: AcquisitionRequest) -> AcquisitionResult:
        search_result = await self._search.search(
            SearchRequest(
                query=request.query,
                max_results=request.max_results,
                schema_version=request.search_schema_version,
                config_version=request.config_version,
            )
        )
        outcomes: list[AcquiredSource] = []
        seen_urls: set[str] = set()
        for item in search_result.items:
            canonical_url = str(item.url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            source_id = self._id_factory("S")
            source = Source(
                source_id=source_id,
                investigation_id=request.investigation_id,
                canonical_url=item.url,
                title=item.title,
                source_type=_SOURCE_TYPES.get(item.source_type_hint or "", SourceType.WEB_PAGE),
                is_official=item.source_type_hint == "official",
                is_first_hand=item.source_type_hint == "official",
                discovered_at=search_result.retrieved_at,
            )
            self._repository.add(source)
            outcome, snapshot, artifacts, gaps = await self._fetch_parse(
                request=request,
                source=source,
                url=canonical_url,
                search_provider=search_result.provider,
                id_factory=self._id_factory,
            )
            self._repository.add_snapshot_bundle(snapshot, artifacts, gaps)
            outcomes.append(outcome)
        return AcquisitionResult(query=request.query, sources=tuple(outcomes))

    async def prepare(
        self, request: AcquisitionRequest, *, logical_step_key: str
    ) -> PreparedAcquisition:
        """Fetch and parse without DB writes; Harness commits returned outputs atomically."""
        search_result = await self._search.search(
            SearchRequest(
                query=request.query,
                max_results=request.max_results,
                schema_version=request.search_schema_version,
                config_version=request.config_version,
            )
        )
        outcomes: list[AcquiredSource] = []
        outputs: list[PersistedEntity] = []
        seen_urls: set[str] = set()
        for item in search_result.items:
            canonical_url = str(item.url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            existing = self._repository.source_by_url(request.investigation_id, canonical_url)
            source = existing or Source(
                source_id=_stable_id("S", request.investigation_id, canonical_url),
                investigation_id=request.investigation_id,
                canonical_url=item.url,
                title=item.title,
                source_type=_SOURCE_TYPES.get(item.source_type_hint or "", SourceType.WEB_PAGE),
                is_official=item.source_type_hint == "official",
                is_first_hand=item.source_type_hint == "official",
                discovered_at=search_result.retrieved_at,
            )
            if existing is None:
                outputs.append(source)
            outcome, snapshot, artifacts, gaps = await self._fetch_parse(
                request=request,
                source=source,
                url=canonical_url,
                search_provider=search_result.provider,
                id_factory=_stable_factory(request.run_id, logical_step_key, canonical_url),
            )
            outcomes.append(outcome)
            outputs.extend((snapshot, *artifacts, *gaps))
        return PreparedAcquisition(
            result=AcquisitionResult(query=request.query, sources=tuple(outcomes)),
            business_outputs=tuple(outputs),
        )

    async def _fetch_parse(
        self,
        *,
        request: AcquisitionRequest,
        source: Source,
        url: str,
        search_provider: str,
        id_factory: IdFactory,
    ) -> tuple[
        AcquiredSource,
        SourceSnapshot,
        tuple[DocumentArtifact, ...],
        tuple[ResearchGap, ...],
    ]:
        fetch_result = await self._fetch.fetch(
            FetchRequest.model_validate(
                {
                    "url": url,
                    "schema_version": request.fetch_schema_version,
                    "config_version": request.config_version,
                }
            )
        )
        snapshot_id = id_factory("SS")
        raw = self._blobs.put_bytes(fetch_result.body)
        parsed = self._parsers.parse(
            DocumentParseRequest(
                snapshot_id=snapshot_id,
                content=fetch_result.body,
                declared_content_type=fetch_result.content_type,
                url=fetch_result.final_url,
            )
        )
        cleaned = (
            self._blobs.put_bytes(parsed.normalized_content)
            if parsed.normalized_content is not None
            else None
        )
        created_at = self._clock()
        artifacts: list[DocumentArtifact] = []
        for parsed_artifact in parsed.artifacts:
            stored = self._blobs.put_bytes(parsed_artifact.content)
            artifacts.append(
                DocumentArtifact(
                    artifact_id=id_factory("A"),
                    snapshot_id=snapshot_id,
                    artifact_type=parsed_artifact.artifact_type,
                    blob_ref=stored.ref,
                    sha256=stored.ref.sha256,
                    processor_name=parsed.parser_name,
                    processor_version=parsed.parser_version,
                    page_number=parsed_artifact.page_number,
                    created_at=created_at,
                )
            )
        gaps = tuple(
            ResearchGap(
                gap_id=id_factory("G"),
                investigation_id=request.investigation_id,
                run_id=request.run_id,
                gap_type=ResearchGapType.UNREADABLE_SOURCE,
                source_id=source.source_id,
                reason=gap.reason,
                severity=(
                    GapSeverity.HIGH
                    if gap.reason == "SCANNED_PDF_REQUIRES_OCR"
                    else GapSeverity.MEDIUM
                ),
                status=GapStatus.OPEN,
                suggested_actions=(gap.details,),
                created_at=created_at,
            )
            for gap in parsed.gaps
        )
        provenance: dict[str, JsonValue] = {
            "search_provider": search_provider,
            "requested_url": url,
            "final_url": str(fetch_result.final_url),
            "declared_content_type": fetch_result.content_type,
            "external_content_trust": parsed.untrusted_content.trust,
            "instruction_detector_version": parsed.untrusted_content.detector_version,
            "suspicious_instruction_detected": (
                parsed.untrusted_content.suspicious_instruction_detected
            ),
            "instruction_finding_codes": list(parsed.untrusted_content.finding_codes),
            "parser_warnings": list(parsed.warnings),
        }
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source_id=source.source_id,
            run_id=request.run_id,
            retrieved_at=fetch_result.fetched_at,
            raw_blob_ref=raw.ref,
            raw_sha256=raw.ref.sha256,
            cleaned_blob_ref=cleaned.ref if cleaned else None,
            cleaned_sha256=cleaned.ref.sha256 if cleaned else None,
            mime_type=parsed.media_type,
            encoding="utf-8" if parsed.normalized_content is not None else None,
            content_size=len(fetch_result.body),
            http_status=fetch_result.status_code,
            parse_status=parsed.parse_status,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            normalizer_version=parsed.normalizer_version,
            evidence_eligible=parsed.evidence_eligible,
            provenance=provenance,
        )
        parsed_ok = parsed.parse_status in {ParseStatus.PARSED, ParseStatus.PARTIALLY_PARSED}
        valid = bool(
            parsed_ok
            and parsed.evidence_eligible
            and artifacts
            and provenance["external_content_trust"] == "UNTRUSTED"
        )
        outcome = AcquiredSource(
            source_id=source.source_id,
            snapshot_id=snapshot_id,
            discovered=True,
            fetched=True,
            parsed=parsed_ok,
            evidence_eligible=parsed.evidence_eligible,
            valid_for_statistics=valid,
            parse_status=parsed.parse_status,
            artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
            gap_ids=tuple(gap.gap_id for gap in gaps),
        )
        return outcome, snapshot, tuple(artifacts), gaps
