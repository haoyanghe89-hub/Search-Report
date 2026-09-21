from __future__ import annotations

import os

import httpx
import pytest

from marketpulse.adapters.search import PublicSearchClient
from marketpulse.budget import RunBudget
from marketpulse.config import Settings
from marketpulse.domain.research import SearchQuery


@pytest.mark.live
@pytest.mark.asyncio
async def test_duckduckgo_search_live() -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 to run")
    settings = Settings.from_env(require_api_key=False)
    budget = RunBudget.start(settings)
    async with httpx.AsyncClient(max_redirects=5) as client:
        search = PublicSearchClient(client, settings, budget)
        results = await search.search(
            SearchQuery(id="live-q1", text="AI meeting notes software pricing", intent="pricing"),
            limit=3,
        )
    assert len(results) >= 1
    assert all(str(item.url).startswith(("https://", "http://")) for item in results)
