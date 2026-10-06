from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, Tag

from marketpulse.investigation.domain.enums import ArtifactType, ParseStatus
from marketpulse.investigation.ingestion.models import (
    DocumentParseRequest,
    GapSuggestion,
    NormalizedDocument,
    ParsedArtifact,
)
from marketpulse.investigation.ingestion.plain_text import NORMALIZER_VERSION, normalize_text
from marketpulse.investigation.ingestion.security import assess_untrusted_content

MIN_BODY_CHARS = 120


def is_html_challenge(soup: BeautifulSoup) -> bool:
    title = normalize_text(soup.title.get_text(" ") if soup.title else "").casefold()
    return bool(
        re.match(
            r"^(just a moment|access denied|attention required|verify (?:that )?you are human)",
            title,
        )
        or soup.select_one("#challenge-form, #cf-challenge-running, #cf-chl-widget")
    )


def _text(node: Tag) -> str:
    return normalize_text(node.get_text("\n"))


def _link_density(node: Tag) -> float:
    return sum(len(link.get_text(" ", strip=True)) for link in node.find_all("a")) / max(
        1, len(_text(node))
    )


def _body_score(node: Tag) -> float:
    # Paragraph-rich bodies beat repeated teaser/navigation cards; never invent text.
    paragraphs = sum(len(_text(p)) for p in node.find_all("p") if len(_text(p)) >= 40)
    # Factual div/span fields beside paragraphs (e.g. official record systems)
    # also count; otherwise a longer paragraph can hide the rest of the record.
    return (paragraphs + 0.2 * len(_text(node))) * max(0, 1 - 2 * _link_density(node))


def _extract_body(soup: BeautifulSoup) -> tuple[str, str]:
    candidates = soup.select(
        "[itemprop='articleBody'], .mw-parser-output, article, main, [role='main']"
    )
    candidates = [node for node in candidates if len(_text(node)) >= MIN_BODY_CHARS]
    if candidates:
        best = max(candidates, key=_body_score)
        return _text(best), "SEMANTIC"
    # Readability-style fallback for pages lacking article/main markup.
    containers: dict[int, Tag] = {}
    for paragraph in soup.find_all("p"):
        ancestor = paragraph.parent
        for _ in range(3):
            if not isinstance(ancestor, Tag) or ancestor.name in {"body", "html", "[document]"}:
                break
            containers[id(ancestor)] = ancestor
            ancestor = ancestor.parent
    candidates = [node for node in containers.values() if len(_text(node)) >= MIN_BODY_CHARS]
    if candidates:
        return _text(max(candidates, key=_body_score)), "PARAGRAPH_DENSITY"
    return _text(soup.body or soup), "CLEAN_BODY"


class HtmlDocumentParser:
    media_types = frozenset({"text/html", "application/xhtml+xml"})
    name = "html"
    version = "3"

    def parse(self, request: DocumentParseRequest) -> NormalizedDocument:
        soup = BeautifulSoup(request.content, "html.parser")
        challenge = is_html_challenge(soup)
        js_shell = bool(
            soup.find("script")
            and (soup.select_one("#root, #app, #__next") or soup.find("noscript"))
        )
        path = urlparse(str(request.url)).path.casefold()
        host = urlparse(str(request.url)).hostname or ""
        search_page = host in {
            "www.google.com",
            "www.bing.com",
            "duckduckgo.com",
            "search.yahoo.com",
        } and (path.startswith("/search") or host == "duckduckgo.com")
        published_article = bool(soup.select_one("meta[property='og:type'][content='article']"))
        navigation_page = (
            not published_article
            and (
                path in {"", "/"}
                or re.search(r"/(?:tags?|category|categories|search)(?:/|$)", path)
            )
            and len(soup.find_all("a")) > 10
        )
        for node in soup(["script", "style", "template", "noscript", "svg"]):
            node.decompose()
        for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
            comment.extract()
        # Assess the full visible page before selecting a body; extraction does not
        # hide suspicious instructions in boilerplate or turn external content trusted.
        assessment = assess_untrusted_content(_text(soup))
        for node in soup.select(
            "head, nav, footer, aside, button, form[role='search'], [hidden], [aria-hidden='true']"
        ):
            node.decompose()
        text, method = _extract_body(soup)
        reason = (
            "CHALLENGE_PAGE"
            if challenge
            else "SEARCH_RESULTS_PAGE"
            if search_page
            else "NAVIGATION_PAGE"
            if navigation_page or _link_density(soup.body or soup) > 0.65
            else "JS_RENDER_REQUIRED"
            if js_shell and len(text) < MIN_BODY_CHARS
            else "EMPTY_CONTENT"
            if not text
            else "BODY_TOO_SHORT"
            if len(text) < MIN_BODY_CHARS
            else None
        )
        warnings = (f"EXTRACTOR_{method}", f"BODY_CHARS={len(text)}")
        if reason:
            return NormalizedDocument(
                media_type="text/html",
                parse_status=ParseStatus.EMPTY_CONTENT
                if not text
                else ParseStatus.INSUFFICIENT_TEXT_LAYER,
                parser_name=self.name,
                parser_version=self.version,
                normalizer_version=NORMALIZER_VERSION,
                evidence_eligible=False,
                untrusted_content=assessment,
                warnings=warnings,
                gaps=(
                    GapSuggestion(
                        reason=reason,
                        details=(
                            f"HTML body rejected ({len(text)} characters); "
                            "find an accessible substantive article."
                        ),
                    ),
                ),
            )
        content = text.encode("utf-8")
        table_artifacts = []
        # Keep real cell/column associations in separately archived, locatable text.
        # No guessed headers for rowspan/colspan tables; preserve those rows literally.
        for table in soup.find_all("table"):
            heading = table.find_previous(["h1", "h2", "h3"])
            document_heading = soup.find("h1")
            caption = table.find("caption")
            context = " | ".join(
                dict.fromkeys(
                    n.get_text(" ", strip=True)
                    for n in (document_heading, heading, caption)
                    if n is not None
                )
            )
            rows = table.find_all("tr")
            headers = []
            lines = []
            for row in rows:
                cells = row.find_all(["th", "td"], recursive=False)
                values = [c.get_text(" ", strip=True) for c in cells]
                if cells and all(c.name == "th" for c in cells):
                    headers = (
                        values
                        if all(
                            c.get("colspan", "1") == "1" and c.get("rowspan", "1") == "1"
                            for c in cells
                        )
                        else []
                    )
                    lines.append(" | ".join([context, *values]))
                elif values:
                    aligned = len(headers) == len(values) and all(
                        c.get("colspan", "1") == "1" and c.get("rowspan", "1") == "1" for c in cells
                    )
                    row_text = (
                        " | ".join(f"{h}: {v}" for h, v in zip(headers, values, strict=True))
                        if aligned
                        else " | ".join(values)
                    )
                    lines.append(" | ".join([context, row_text]))
            if lines:
                table_artifacts.append(
                    ParsedArtifact(
                        artifact_type=ArtifactType.HTML_NORMALIZED_TEXT,
                        content=normalize_text("\n".join(lines)).encode("utf-8"),
                    )
                )
        return NormalizedDocument(
            media_type="text/html",
            parse_status=ParseStatus.PARSED,
            parser_name=self.name,
            parser_version=self.version,
            normalizer_version=NORMALIZER_VERSION,
            normalized_content=content,
            artifacts=(
                ParsedArtifact(artifact_type=ArtifactType.HTML_NORMALIZED_TEXT, content=content),
                *table_artifacts,
            ),
            evidence_eligible=True,
            untrusted_content=assessment,
            warnings=warnings,
        )
