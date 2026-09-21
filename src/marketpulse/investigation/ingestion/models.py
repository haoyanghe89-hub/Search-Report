from __future__ import annotations

from typing import Protocol

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus


class IngestionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", ser_json_bytes="base64")


class DocumentParseRequest(IngestionModel):
    snapshot_id: str = Field(min_length=1)
    content: bytes
    declared_content_type: str = ""
    url: AnyHttpUrl


class UntrustedContentAssessment(IngestionModel):
    trust: str = "UNTRUSTED"
    detector_version: str
    suspicious_instruction_detected: bool
    finding_codes: tuple[str, ...] = ()


class ParsedArtifact(IngestionModel):
    artifact_type: ArtifactType
    content: bytes
    page_number: int | None = Field(default=None, ge=1)
    reliable: bool = True


class GapSuggestion(IngestionModel):
    reason: str = Field(min_length=1)
    details: str = Field(min_length=1)


class NormalizedDocument(IngestionModel):
    media_type: str = Field(min_length=1)
    parse_status: ParseStatus
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    normalizer_version: str = Field(min_length=1)
    normalized_content: bytes | None = None
    artifacts: tuple[ParsedArtifact, ...] = ()
    evidence_eligible: bool
    untrusted_content: UntrustedContentAssessment
    warnings: tuple[str, ...] = ()
    gaps: tuple[GapSuggestion, ...] = ()


class DocumentParserPort(Protocol):
    media_types: frozenset[str]

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument: ...
