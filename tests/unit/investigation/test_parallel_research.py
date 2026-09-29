from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from marketpulse.investigation.agents.contracts import BudgetView, ResearchInput, TaskProposal
from marketpulse.investigation.feedback.parallel import bounded_map
from marketpulse.investigation.feedback.research_team import research_team
from marketpulse.investigation.ports.external import StructuredModelResult


@pytest.mark.asyncio
async def test_workers_overlap_but_never_exceed_limit_and_preserve_order() -> None:
    active = peak = 0
    gate = asyncio.Event()

    async def work(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 3:
            gate.set()
        await asyncio.wait_for(gate.wait(), 1)
        await asyncio.sleep(0)
        active -= 1
        return value

    assert await bounded_map(list(range(9)), work, 3) == list(range(9))
    assert peak == 3
    assert active == 0


@pytest.mark.asyncio
async def test_failure_drains_siblings_and_does_not_start_queued_work() -> None:
    started: list[int] = []
    stopped: list[int] = []

    async def work(value: int) -> int:
        started.append(value)
        try:
            if value == 0:
                await asyncio.sleep(0)
                raise RuntimeError("provider failed")
            await asyncio.Event().wait()
            return value
        finally:
            stopped.append(value)

    with pytest.raises(RuntimeError, match="provider failed"):
        await bounded_map(list(range(10)), work, 2)
    assert sorted(started) == sorted(stopped)
    assert len(started) < 10


@pytest.mark.asyncio
async def test_research_specialists_overlap_and_merge_unique_queries_fairly() -> None:
    contexts: list[dict[str, Any]] = []
    gate = asyncio.Event()

    class Model:
        def __init__(self, name: str) -> None:
            self.name = name

        async def generate(self, request: Any) -> Any:
            context = json.loads(request.messages[1].content)["bounded_context"]
            contexts.append(context)
            if len(contexts) == 4:
                gate.set()
            await asyncio.wait_for(gate.wait(), 1)
            return StructuredModelResult(
                output=request.response_model.model_validate(
                    {
                        "queries": [
                            {
                                "query_key": "unique",
                                "query": self.name + " outage cause",
                                "target_question_key": "q",
                                "purpose": "evidence",
                                "max_results": 2,
                            },
                            {
                                "query_key": "shared",
                                "query": "shared outage evidence",
                                "target_question_key": "q",
                                "purpose": "evidence",
                                "max_results": 2,
                            },
                        ]
                    }
                ),
                provider="test",
                model="test",
            )

    request = ResearchInput(
        task=TaskProposal(
            task_key="task", target_question_key="q", objective="Find cause", priority=80
        ),
        remaining_search_calls=5,
        budget=BudgetView(model_calls_remaining=20),
    )
    proposal, errors = await research_team(request, Model, workers=4, max_queries=2)
    assert len(contexts) == 4
    assert len({context["task"]["objective"] for context in contexts}) == 4
    assert len(proposal.queries) == 5
    assert [q.query_key.split(":")[0] for q in proposal.queries[:4]] == [
        "official",
        "independent",
        "technical",
        "counterevidence",
    ]
    assert len({q.query for q in proposal.queries}) == 5
    assert not errors


@pytest.mark.asyncio
async def test_blocked_source_becomes_gap_without_cancelling_other_fetches(tmp_path: Path) -> None:
    from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
    from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
    from marketpulse.investigation.ports.external import FetchResult, SearchResult
    from marketpulse.investigation.recording.errors import SecurityBlockedError
    from marketpulse.investigation.services.source_acquisition import (
        AcquisitionRequest,
        SourceAcquisitionService,
    )

    active = peak = 0
    gate = asyncio.Event()

    class Fetch:
        async def fetch(self, request: Any) -> FetchResult:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                gate.set()
            try:
                await asyncio.wait_for(gate.wait(), 1)
                if str(request.url).endswith("/blocked"):
                    raise SecurityBlockedError("sensitive provider detail")
                return FetchResult(
                    final_url=request.url,
                    status_code=200,
                    content_type="text/plain",
                    body=b"Independent public event source.",
                    fetched_at=datetime.now(UTC),
                )
            finally:
                active -= 1

    repository = Mock()
    repository.source_by_url.return_value = None
    service = SourceAcquisitionService(
        repository=repository,
        blobs=LocalContentAddressedBlobStorage(tmp_path / "blobs"),
        search=Mock(),
        fetch=Fetch(),
        parsers=DocumentParserRegistry.default(),
        fetch_concurrency=2,
        tolerate_fetch_errors=True,
    )
    found = SearchResult.model_validate(
        {
            "provider": "test",
            "retrieved_at": datetime.now(UTC),
            "items": [
                {"title": "source", "url": "https://example.org/" + p, "rank": i + 1}
                for i, p in enumerate(["blocked", "public"])
            ],
        }
    )
    prepared = await service.prepare(
        AcquisitionRequest(investigation_id="inv", run_id="run", query="event"),
        logical_step_key="research",
        search_result=found,
    )
    assert peak == 2 and active == 0
    assert not prepared.result.sources[0].fetched
    assert prepared.result.sources[0].gap_ids
    assert prepared.result.sources[1].fetched
    assert "sensitive provider detail" not in repr(prepared.business_outputs)


@pytest.mark.asyncio
async def test_verifiers_work_on_disjoint_claim_groups() -> None:
    from marketpulse.investigation.agents.contracts import ClaimCandidate, VerificationInput
    from marketpulse.investigation.feedback.verification_team import verification_team

    seen: list[list[str]] = []
    gate = asyncio.Event()

    class Model:
        async def generate(self, request: Any) -> Any:
            context = json.loads(request.messages[1].content)["bounded_context"]
            seen.append([claim["claim_key"] for claim in context["claims"]])
            if len(seen) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), 1)
            return StructuredModelResult(
                output=request.response_model.model_validate({}), provider="test", model="test"
            )

    await verification_team(
        VerificationInput(
            claims=tuple(
                ClaimCandidate(
                    claim_key=str(i), statement="An attributed statement.", claim_type="STATEMENT"
                )
                for i in range(4)
            ),
            evidence=(),
        ),
        lambda _: Model(),
        workers=2,
    )
    assert len(seen) == 2
    assert set(seen[0]).isdisjoint(seen[1])
    assert sorted(key for batch in seen for key in batch) == ["C1", "C2", "C3", "C4"]


@pytest.mark.asyncio
async def test_batch_deduplicates_urls_and_allocates_page_budget_before_fetch() -> None:
    from marketpulse.investigation.agents.contracts import QueryIntent
    from marketpulse.investigation.feedback.acquisition_batch import acquisition_batch
    from marketpulse.investigation.ports.external import SearchResult
    from marketpulse.investigation.services.source_acquisition import (
        AcquisitionResult,
        PreparedAcquisition,
    )

    captured: list[str] = []

    class Search:
        async def search(self, request: Any) -> SearchResult:
            return SearchResult.model_validate(
                {
                    "provider": "test",
                    "retrieved_at": datetime.now(UTC),
                    "items": [
                        {"title": "test", "url": url, "rank": i + 1}
                        for i, url in enumerate(
                            ["https://example.com/shared", f"https://example.com/{request.query}"]
                        )
                    ],
                }
            )

    class Service:
        async def prepare(self, request: Any, **kwargs: Any) -> PreparedAcquisition:
            captured.extend(str(item.url) for item in kwargs["search_result"].items)
            return PreparedAcquisition(
                result=AcquisitionResult(query=request.query, sources=()), business_outputs=()
            )

    queries = [
        QueryIntent(
            query_key=str(i),
            query=str(i),
            target_question_key="q",
            purpose="evidence",
            max_results=2,
        )
        for i in range(4)
    ]
    _, errors = await acquisition_batch(
        queries,
        search=lambda _: Search(),
        service=lambda *_: Service(),
        investigation_id="inv",
        run_id="run",
        logical_key="research",
        search_limit=2,
        fetch_limit=2,
        page_budget=3,
    )
    assert len(captured) == len(set(captured)) == 3
    assert not errors
