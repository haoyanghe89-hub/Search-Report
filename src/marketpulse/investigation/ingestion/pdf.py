from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import FileNotDecryptedError, PdfReadError

from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus
from marketpulse.investigation.ingestion.models import (
    DocumentParseRequest,
    GapSuggestion,
    NormalizedDocument,
    ParsedArtifact,
)
from marketpulse.investigation.ingestion.plain_text import NORMALIZER_VERSION, normalize_text
from marketpulse.investigation.ingestion.security import assess_untrusted_content

_MIN_MEANINGFUL_PAGE_CHARS = 40


class PdfTextLayerParser:
    media_types = frozenset({"application/pdf"})
    name = "pypdf-text-layer"
    version = "1"

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument:
        empty_assessment = assess_untrusted_content("")
        try:
            reader = PdfReader(BytesIO(request.content), strict=False)
        except PdfReadError:
            return self._unusable(ParseStatus.CORRUPT_DOCUMENT, "CORRUPT_PDF")
        except Exception:
            return self._unusable(ParseStatus.PARSE_FAILED, "PDF_PARSE_FAILED")
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    return self._unusable(ParseStatus.ENCRYPTED_PDF, "ENCRYPTED_PDF")
            except Exception:
                return self._unusable(ParseStatus.ENCRYPTED_PDF, "ENCRYPTED_PDF")
        if not reader.pages:
            return NormalizedDocument(
                media_type="application/pdf",
                parse_status=ParseStatus.EMPTY_CONTENT,
                parser_name=self.name,
                parser_version=self.version,
                normalizer_version=NORMALIZER_VERSION,
                evidence_eligible=False,
                untrusted_content=empty_assessment,
                gaps=(GapSuggestion(reason="EMPTY_CONTENT", details="The PDF has no pages."),),
            )

        artifacts: list[ParsedArtifact] = []
        extracted_chars = 0
        failed_pages: list[int] = []
        small_text_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = normalize_text(page.extract_text() or "")
            except (PdfReadError, FileNotDecryptedError, ValueError, TypeError):
                failed_pages.append(page_number)
                continue
            extracted_chars += len(text)
            meaningful_chars = sum(character.isalnum() for character in text)
            if meaningful_chars < _MIN_MEANINGFUL_PAGE_CHARS:
                small_text_pages.append(page_number)
                continue
            artifacts.append(
                ParsedArtifact(
                    artifact_type=ArtifactType.PDF_PAGE_TEXT,
                    content=text.encode("utf-8"),
                    page_number=page_number,
                )
            )

        if not artifacts:
            if extracted_chars == 0:
                return self._unusable(
                    ParseStatus.UNSUPPORTED_SCANNED_PDF,
                    "SCANNED_PDF_REQUIRES_OCR",
                )
            return self._unusable(
                ParseStatus.INSUFFICIENT_TEXT_LAYER,
                "INSUFFICIENT_PDF_TEXT_LAYER",
            )

        unreadable = tuple(sorted({*failed_pages, *small_text_pages}))
        status = ParseStatus.PARTIALLY_PARSED if unreadable else ParseStatus.PARSED
        aggregate = "\n\n".join(
            f"[Page {artifact.page_number}]\n{artifact.content.decode()}" for artifact in artifacts
        ).encode("utf-8")
        assessment = assess_untrusted_content(aggregate.decode())
        gaps: tuple[GapSuggestion, ...] = ()
        warnings: tuple[str, ...] = ()
        if unreadable:
            page_list = ", ".join(str(page) for page in unreadable)
            gaps = (
                GapSuggestion(
                    reason="PDF_PAGES_WITHOUT_RELIABLE_TEXT",
                    details=f"Pages without reliable text: {page_list}.",
                ),
            )
            warnings = (f"UNREADABLE_PDF_PAGES:{page_list}",)
        return NormalizedDocument(
            media_type="application/pdf",
            parse_status=status,
            parser_name=self.name,
            parser_version=self.version,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content=aggregate,
            artifacts=tuple(artifacts),
            evidence_eligible=True,
            untrusted_content=assessment,
            warnings=warnings,
            gaps=gaps,
        )

    def _unusable(self, status: ParseStatus, reason: str) -> NormalizedDocument:
        return NormalizedDocument(
            media_type="application/pdf",
            parse_status=status,
            parser_name=self.name,
            parser_version=self.version,
            normalizer_version=NORMALIZER_VERSION,
            evidence_eligible=False,
            untrusted_content=assess_untrusted_content(""),
            gaps=(
                GapSuggestion(
                    reason=reason,
                    details="The PDF does not expose a reliable V1 text layer.",
                ),
            ),
        )
