"""Stable search fan-out followed by deduplicated, bounded fetch fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from marketpulse.investigation.agents.contracts import QueryIntent
from marketpulse.investigation.feedback.parallel import bounded_map
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.ports.external import (
    SearchPort,
    SearchRequest,
    SearchResult,
    SearchResultItem,
)
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    PreparedAcquisition,
    SourceAcquisitionService,
)


async def acquisition_batch(
    queries: Sequence[QueryIntent],
    *,
    search: Callable[[str], SearchPort],
    service: Callable[[str, asyncio.Semaphore], SourceAcquisitionService],
    investigation_id: str,
    run_id: str,
    logical_key: str,
    search_limit: int,
    fetch_limit: int,
    page_budget: int,
) -> tuple[list[PreparedAcquisition], tuple[str, ...]]:
    indexed = list(enumerate(queries))

    async def discover(entry: tuple[int, QueryIntent]) -> SearchResult | Exception:
        index, intent = entry
        try:
            return await search(f"research.search.q{index}").search(
                SearchRequest(
                    query=intent.query,
                    max_results=min(intent.max_results, page_budget),
                )
            )
        except RunBudgetExceededError:
            raise
        except Exception as error:
            return error

    results = await bounded_map(indexed, discover, search_limit)
    seen: set[str] = set()
    selected: list[list[SearchResultItem]] = [[] for _ in queries]
    # Allocate pages round-robin so one perspective cannot consume the entire budget.
    for rank in range(
        max((len(r.items) for r in results if isinstance(r, SearchResult)), default=0)
    ):
        for index, result in enumerate(results):
            if isinstance(result, Exception) or rank >= len(result.items):
                continue
            item = result.items[rank]
            if str(item.url) in seen or len(seen) >= page_budget:
                continue
            seen.add(str(item.url))
            selected[index].append(item)
    semaphore = asyncio.Semaphore(fetch_limit)

    async def acquire(entry: tuple[int, QueryIntent]) -> PreparedAcquisition | None:
        index, intent = entry
        result = results[index]
        if isinstance(result, Exception) or not selected[index]:
            return None
        return await service(f"research.fetch.q{index}", semaphore).prepare(
            AcquisitionRequest(
                investigation_id=investigation_id,
                run_id=run_id,
                query=intent.query,
                max_results=min(intent.max_results, page_budget),
            ),
            logical_step_key=logical_key,
            search_result=result.model_copy(update={"items": tuple(selected[index])}),
        )

    prepared = await bounded_map(indexed, acquire, search_limit)
    return [item for item in prepared if item is not None], tuple(
        f"search.q{index}:{type(result).__name__}"
        for index, result in enumerate(results)
        if isinstance(result, Exception)
    )
