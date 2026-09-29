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


class PublicSearchPortAdapter:
    """Legacy provider bridge kept outside the Investigation package boundary."""

    def __init__(self, client: SearchClient, *, provider: str = "public-search") -> None:
        self._client = client
        self._provider = provider

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
                            else "web"
                            if candidate.source_hint == "official"
                            else candidate.source_hint
                        ),
                        "is_official": _government_host(str(candidate.url)),
                        "is_first_hand": False,
                    }
                )
                for candidate in candidates
            ),
            provider=self._provider,
            retrieved_at=datetime.now(UTC),
        )


def _government_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return re.search(r"(?:^|\.)gov(?:\.[a-z]{2})?$", host) is not None
