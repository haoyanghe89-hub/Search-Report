from __future__ import annotations

import hashlib

from marketpulse.investigation.domain.locators import PdfTextRangeLocator, TextRangeLocator


class LocatorResolutionError(ValueError):
    code = "LOCATOR_RESOLUTION_ERROR"


def _quote_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_text_locator(text: str, start: int, end: int) -> TextRangeLocator:
    return TextRangeLocator(start=start, end=end, quote_hash=_quote_hash(text[start:end]))


def make_pdf_locator(text: str, *, page: int, start: int, end: int) -> PdfTextRangeLocator:
    return PdfTextRangeLocator(
        page=page,
        start=start,
        end=end,
        quote_hash=_quote_hash(text[start:end]),
    )


def resolve_locator(
    locator: TextRangeLocator | PdfTextRangeLocator,
    artifact_content: bytes,
    *,
    page_number: int | None = None,
) -> str:
    try:
        text = artifact_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LocatorResolutionError("artifact is not normalized UTF-8 text") from error
    if isinstance(locator, PdfTextRangeLocator) and page_number != locator.page:
        raise LocatorResolutionError("PDF locator page does not match artifact page")
    if locator.end > len(text):
        raise LocatorResolutionError("locator exceeds artifact text")
    quote = text[locator.start : locator.end]
    if _quote_hash(quote) != locator.quote_hash:
        raise LocatorResolutionError("locator quote hash does not match artifact text")
    return quote
