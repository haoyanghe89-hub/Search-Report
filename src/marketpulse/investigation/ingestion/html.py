from __future__ import annotations

from bs4 import BeautifulSoup, Comment

from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus
from marketpulse.investigation.ingestion.models import (
    DocumentParseRequest,
    GapSuggestion,
    NormalizedDocument,
    ParsedArtifact,
)
from marketpulse.investigation.ingestion.plain_text import NORMALIZER_VERSION, normalize_text
from marketpulse.investigation.ingestion.security import assess_untrusted_content


class HtmlDocumentParser:
    media_types = frozenset({"text/html", "application/xhtml+xml"})
    name = "html"
    version = "1"

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument:
        decoded = request.content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(decoded, "html.parser")
        for node in soup(["script", "style", "template", "noscript", "svg"]):
            node.decompose()
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()
        text = normalize_text(soup.get_text("\n"))
        assessment = assess_untrusted_content(text)
        if not text:
            return NormalizedDocument(
                media_type="text/html",
                parse_status=ParseStatus.EMPTY_CONTENT,
                parser_name=self.name,
                parser_version=self.version,
                normalizer_version=NORMALIZER_VERSION,
                evidence_eligible=False,
                untrusted_content=assessment,
                gaps=(
                    GapSuggestion(reason="EMPTY_CONTENT", details="No usable HTML text was found."),
                ),
            )
        content = text.encode("utf-8")
        return NormalizedDocument(
            media_type="text/html",
            parse_status=ParseStatus.PARSED,
            parser_name=self.name,
            parser_version=self.version,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content=content,
            artifacts=(
                ParsedArtifact(artifact_type=ArtifactType.HTML_NORMALIZED_TEXT, content=content),
            ),
            evidence_eligible=True,
            untrusted_content=assessment,
        )
