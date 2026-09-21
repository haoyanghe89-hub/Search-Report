from __future__ import annotations

import re
import unicodedata

from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus
from marketpulse.investigation.ingestion.models import (
    DocumentParseRequest,
    GapSuggestion,
    NormalizedDocument,
    ParsedArtifact,
)
from marketpulse.investigation.ingestion.security import assess_untrusted_content

NORMALIZER_VERSION = "text-normalizer-v1"


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\x00", "")
    lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in value.split("\n")]
    value = "\n".join(lines)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


class PlainTextDocumentParser:
    media_types = frozenset({"text/plain"})
    name = "plain-text"
    version = "1"

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument:
        warnings: list[str] = []
        try:
            decoded = request.content.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = request.content.decode("utf-8", errors="replace")
            warnings.append("INVALID_UTF8_REPLACED")
        text = normalize_text(decoded)
        assessment = assess_untrusted_content(text)
        if not text:
            return NormalizedDocument(
                media_type="text/plain",
                parse_status=ParseStatus.EMPTY_CONTENT,
                parser_name=self.name,
                parser_version=self.version,
                normalizer_version=NORMALIZER_VERSION,
                evidence_eligible=False,
                untrusted_content=assessment,
                warnings=tuple(warnings),
                gaps=(GapSuggestion(reason="EMPTY_CONTENT", details="No usable text was found."),),
            )
        content = text.encode("utf-8")
        return NormalizedDocument(
            media_type="text/plain",
            parse_status=ParseStatus.PARSED,
            parser_name=self.name,
            parser_version=self.version,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content=content,
            artifacts=(ParsedArtifact(artifact_type=ArtifactType.PLAIN_TEXT, content=content),),
            evidence_eligible=True,
            untrusted_content=assessment,
            warnings=tuple(warnings),
        )
