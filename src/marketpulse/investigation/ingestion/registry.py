from __future__ import annotations

from urllib.parse import urlparse

from marketpulse.investigation.ingestion.html import HtmlDocumentParser
from marketpulse.investigation.ingestion.models import (
    DocumentParseRequest,
    DocumentParserPort,
    NormalizedDocument,
)
from marketpulse.investigation.ingestion.pdf import PdfTextLayerParser
from marketpulse.investigation.ingestion.plain_text import PlainTextDocumentParser


class UnsupportedDocumentTypeError(ValueError):
    code = "UNSUPPORTED_MEDIA_TYPE"


def detect_media_type(request: DocumentParseRequest) -> str:
    content = request.content
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    prefix = content[:4096].lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    declared = request.declared_content_type.split(";", 1)[0].strip().casefold()
    if declared in {"text/html", "application/xhtml+xml", "text/plain", "application/pdf"}:
        return declared
    suffix = urlparse(str(request.url)).path.casefold()
    if suffix.endswith(".pdf"):
        return "application/pdf"
    if suffix.endswith((".html", ".htm")):
        return "text/html"
    if suffix.endswith(".txt"):
        return "text/plain"
    if content:
        return "text/plain"
    raise UnsupportedDocumentTypeError("cannot determine media type")


class DocumentParserRegistry:
    def __init__(self, parsers: tuple[DocumentParserPort, ...]) -> None:
        self._parsers = {
            media_type: parser for parser in parsers for media_type in parser.media_types
        }

    @classmethod
    def default(cls) -> DocumentParserRegistry:
        return cls((HtmlDocumentParser(), PlainTextDocumentParser(), PdfTextLayerParser()))

    def parser_for(self, request: DocumentParseRequest) -> DocumentParserPort:
        media_type = detect_media_type(request)
        try:
            return self._parsers[media_type]
        except KeyError as error:
            raise UnsupportedDocumentTypeError(media_type) from error

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument:
        return self.parser_for(request).parse(request)
