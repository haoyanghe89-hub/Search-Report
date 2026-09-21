from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    RunMode,
    RunStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.ingestion.locators import make_text_locator, resolve_locator
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    SearchRequest,
    SearchResult,
    SearchResultItem,
)
from marketpulse.investigation.recording.adapters import (
    CallContext,
    RecordingFetchAdapter,
    RecordingSearchAdapter,
    ReplayFetchAdapter,
    ReplaySearchAdapter,
)
from marketpulse.investigation.recording.canonical import request_fingerprint
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    SourceAcquisitionService,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


def _seed(repository: InvestigationRepository, suffix: str, mode: RunMode) -> None:
    repository.add(
        Investigation(
            investigation_id=f"I-{suffix}",
            title=f"Investigation {suffix}",
            event_description="A public event.",
            investigation_goal="Acquire traceable sources.",
            scope=InvestigationScope(summary="Public sources"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id=f"RUN-{suffix}",
            investigation_id=f"I-{suffix}",
            mode=mode,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="acquisition-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        ExecutionStep(
            step_id=f"STEP-{suffix}",
            run_id=f"RUN-{suffix}",
            step_type=StepType.FETCH,
            agent_role=AgentRole.HARNESS,
            status=ExecutionStepStatus.RUNNING,
            attempt=1,
            input_fingerprint=request_fingerprint(
                "search", SearchRequest(query="East Palestine official report", max_results=1)
            ),
            retryable=True,
        )
    )


class SearchFixture:
    calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        return SearchResult(
            items=(
                SearchResultItem(
                    title="Official incident report",
                    url="https://agency.example/report.pdf",
                    snippet="Official findings",
                    rank=1,
                    source_type_hint="official",
                ),
            ),
            provider="fixture-search",
            retrieved_at=NOW,
        )


class FetchFixture:
    calls = 0

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.calls += 1
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/html",
            body=(
                b"<html><body><h1>Finding</h1><p>The train derailed at 8:54 p.m.</p></body></html>"
            ),
            fetched_at=NOW,
        )


def _ids(prefix: str):  # type: ignore[no-untyped-def]
    counters: dict[str, int] = {}

    def factory(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{prefix}-{kind}-{counters[kind]:03d}"

    return factory


@pytest.mark.asyncio
async def test_live_then_replay_acquisition_rebuilds_snapshot_and_exact_locator(
    investigation_store: tuple[InvestigationRepository, object, str], tmp_path: Path
) -> None:
    repository, _, _ = investigation_store
    _seed(repository, "LIVE", RunMode.LIVE)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    calls = RepositoryRecordedCallStore(repository, blobs)
    live_search = SearchFixture()
    live_fetch = FetchFixture()
    search = RecordingSearchAdapter(
        live_search, calls, CallContext("RUN-LIVE", "STEP-LIVE"), clock=lambda: NOW
    )
    fetch = RecordingFetchAdapter(
        live_fetch,
        calls,
        CallContext("RUN-LIVE", "STEP-LIVE", provider="fixture-fetch"),
        clock=lambda: NOW,
    )
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=search,
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        id_factory=_ids("LIVE"),
        clock=lambda: NOW,
    )
    request = AcquisitionRequest(
        investigation_id="I-LIVE",
        run_id="RUN-LIVE",
        query="East Palestine official report",
        max_results=1,
    )
    live_result = await service.acquire(request)
    live_source = live_result.sources[0]
    artifact = repository.list_artifacts(live_source.snapshot_id)[0]  # type: ignore[arg-type]
    artifact_content = blobs.get_bytes(artifact.blob_ref)
    text = artifact_content.decode()
    start = text.index("train derailed")
    locator = make_text_locator(text, start, start + len("train derailed"))

    assert live_source.valid_for_statistics is True
    assert resolve_locator(locator, artifact_content) == "train derailed"
    assert (
        len(
            repository.list_replayable_tool_calls(
                run_id="RUN-LIVE",
                operation="search",
                request_fingerprint=request_fingerprint(
                    "search", SearchRequest(query=request.query, max_results=1)
                ),
            )
        )
        == 1
    )

    _seed(repository, "REPLAY", RunMode.REPLAY)
    replay_service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=ReplaySearchAdapter(calls, source_run_id="RUN-LIVE"),
        fetch=ReplayFetchAdapter(calls, source_run_id="RUN-LIVE"),
        parsers=DocumentParserRegistry.default(),
        id_factory=_ids("REPLAY"),
        clock=lambda: NOW,
    )
    replay_result = await replay_service.acquire(
        request.model_copy(update={"investigation_id": "I-REPLAY", "run_id": "RUN-REPLAY"})
    )

    assert replay_result.sources[0].valid_for_statistics is True
    assert replay_result.sources[0].snapshot_id != live_source.snapshot_id
    assert live_search.calls == 1
    assert live_fetch.calls == 1
