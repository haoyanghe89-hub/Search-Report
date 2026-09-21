from __future__ import annotations

import asyncio

from marketpulse.adapters.fetch import FetchedPage, PageFetcher
from marketpulse.adapters.search import SearchClient, canonicalize_url
from marketpulse.domain.research import SearchCandidate, SearchQuery
from marketpulse.errors import BudgetExceeded, SearchUnavailableError


async def collect_candidates(
    queries: list[SearchQuery], search: SearchClient, *, per_query: int = 6
) -> tuple[list[SearchCandidate], list[str]]:
    candidates: dict[str, SearchCandidate] = {}
    warnings: list[str] = []
    for query in queries:
        try:
            batch = await search.search(query, limit=per_query)
        except BudgetExceeded:
            warnings.append("搜索预算已耗尽")
            break
        except SearchUnavailableError as exc:
            warnings.append(str(exc))
            continue
        for candidate in batch:
            try:
                canonical = canonicalize_url(str(candidate.url))
            except ValueError:
                continue
            candidates.setdefault(canonical, candidate)
    ordered = sorted(
        candidates.values(),
        key=lambda item: (item.source_hint != "official", item.rank, str(item.url)),
    )
    return ordered, warnings


async def fetch_candidates(
    candidates: list[SearchCandidate],
    fetcher: PageFetcher,
    *,
    max_pages: int,
    concurrency: int,
) -> tuple[list[FetchedPage], list[str]]:
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(candidate: SearchCandidate) -> tuple[FetchedPage | None, str | None]:
        async with semaphore:
            try:
                return await fetcher.fetch(candidate), None
            except BudgetExceeded:
                return None, "页面预算已耗尽"
            except Exception as exc:
                return None, f"{candidate.url}: {type(exc).__name__}: {exc}"

    results = await asyncio.gather(*(fetch_one(item) for item in candidates[:max_pages]))
    pages = [page for page, _ in results if page is not None]
    warnings = [warning for _, warning in results if warning is not None]
    pages.sort(key=lambda page: str(page.candidate.url))
    return pages, warnings
