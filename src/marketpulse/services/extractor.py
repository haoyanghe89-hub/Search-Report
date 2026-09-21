from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from marketpulse.adapters.fetch import FetchedPage
from marketpulse.domain.evidence import EvidenceClaim, PageEvidence, Source, SourceType

_KEYWORDS = {
    "pricing": ("$", "€", "£", "pricing", "price", "per month", "monthly", "annual"),
    "feature": ("feature", "integration", "transcription", "summary", "automation", "workflow"),
    "customer": ("customer", "team", "business", "enterprise", "professional", "user"),
    "demand": ("market", "growth", "adoption", "demand", "trend", "survey"),
}


def extract_visible_text(page: FetchedPage) -> str:
    if page.content_type == "text/plain":
        text = page.body.decode("utf-8", errors="replace")
    else:
        soup = BeautifulSoup(page.body, "html.parser")
        for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
            node.decompose()
        text = soup.get_text("\n", strip=True)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if len(line) < 20 or line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return "\n".join(deduped)[:40_000]


def _claim_type(text: str) -> str:
    lowered = text.casefold()
    for claim_type, keywords in _KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return claim_type
    return "product"


def build_page_evidence(page: FetchedPage, source_index: int) -> PageEvidence:
    text = extract_visible_text(page)
    if len(text) < 80:
        raise ValueError("页面正文过短")
    source_id = f"S{source_index}"
    hostname = urlparse(page.final_url).hostname or ""
    source_type = (
        SourceType.OFFICIAL if page.candidate.source_hint == "official" else SourceType.OTHER
    )
    source = Source.model_validate(
        {
            "id": source_id,
            "url": page.final_url,
            "title": page.candidate.title,
            "domain": hostname,
            "source_type": source_type,
            "accessed_at": page.fetched_at,
            "query_id": page.candidate.query_id,
        }
    )
    segments = [item.strip() for item in re.split(r"[\n。]+", text) if len(item.strip()) >= 30]
    scored = sorted(
        enumerate(segments),
        key=lambda pair: (
            -sum(
                keyword in pair[1].casefold()
                for keywords in _KEYWORDS.values()
                for keyword in keywords
            ),
            pair[0],
        ),
    )
    selected = [segment for _, segment in scored[:6]]
    claims = [
        EvidenceClaim(
            id=f"C{source_index}_{claim_index}",
            source_id=source_id,
            claim_type=_claim_type(segment),
            subject=page.candidate.title[:200],
            statement=segment[:500],
            quote=segment[:500],
        )
        for claim_index, segment in enumerate(selected, start=1)
    ]
    return PageEvidence(source=source, claims=claims, extracted_text=text)
