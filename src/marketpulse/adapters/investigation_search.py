from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from marketpulse.adapters.search import SearchClient
from marketpulse.domain.research import SearchQuery
from marketpulse.investigation.ports.external import (
    SearchRequest,
    SearchResult,
    SearchResultItem,
)

# Exact issuer-owned publication hosts, not authority scores or a query substring
# heuristic. Shared hosting (e.g. storage.googleapis.com) is deliberately excluded.
_DIRECT_PUBLISHERS = {
    "deepmind.google": "Google",
    "blog.google": "Google",
    "developers.googleblog.com": "Google",
}


class PublicSearchPortAdapter:
    """Legacy provider bridge kept outside the Investigation package boundary."""

    def __init__(
        self,
        client: SearchClient,
        *,
        provider: str = "public-search",
        direct_publishers: dict[str, str] | None = None,
    ) -> None:
        self._client = client
        self._provider = provider
        self._direct_publishers = dict(
            _DIRECT_PUBLISHERS if direct_publishers is None else direct_publishers
        )

    async def search(self, request: SearchRequest) -> SearchResult:
        query_id = f"Q-{hashlib.sha256(request.query.encode()).hexdigest()[:16]}"
        legacy_query = SearchQuery(id=query_id, text=request.query, intent="product")
        candidates = await self._client.search(legacy_query, limit=request.max_results)
        return SearchResult(
            items=tuple(
                SearchResultItem.model_validate(
                    {
                        "title": candidate.title,
                        "url": str(candidate.url),
                        "snippet": candidate.snippet,
                        "rank": candidate.rank,
                        # The legacy provider guesses "official" from query/domain
                        # substring overlap. That is discovery metadata, not provenance.
                        "source_type_hint": (
                            "official"
                            if _government_host(str(candidate.url))
                            or self._publisher(str(candidate.url))
                            else "web"
                            if candidate.source_hint == "official"
                            else candidate.source_hint
                        ),
                        "is_official": _government_host(str(candidate.url))
                        or bool(self._publisher(str(candidate.url))),
                        # An issuer's own publication is first-hand for what it reports,
                        # not independent proof of its performance claims.
                        "is_first_hand": bool(self._publisher(str(candidate.url))),
                        "publisher": self._publisher(str(candidate.url)),
                        "organization": self._publisher(str(candidate.url)),
                        "quality_metadata": {
                            "publisher_family": "issuer:" + self._publisher(str(candidate.url))
                        }
                        if self._publisher(str(candidate.url))
                        else {},
                    }
                )
                for candidate in candidates
            ),
            provider=self._provider,
            retrieved_at=datetime.now(UTC),
        )

    def _publisher(self, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            return None
        return self._direct_publishers.get((parsed.hostname or "").lower().rstrip("."))


def _government_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return re.search(r"(?:^|\.)gov(?:\.[a-z]{2})?$", host) is not None
