from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.enums import (
    AgentRole,
    RunMode,
    RunStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
    RunBudget,
)
from marketpulse.investigation.domain.sources import Source, SourceSnapshot
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    FetchRequest,
    FetchResult,
    SearchRequest,
    SearchResult,
    SearchResultItem,
)
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    SourceAcquisitionService,
)

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class SearchFixture:
    async def search(self, request: SearchRequest) -> SearchResult:
        return SearchResult(
            items=(
                SearchResultItem(
                    title="Official record",
                    url="https://agency.example/report",
                    rank=1,
                    source_type_hint="official",
                ),
            ),
            provider="fixture",
            retrieved_at=NOW,
        )


class FetchFixture:
    def __init__(self, repository: InvestigationRepository) -> None:
        self.repository = repository
        self.saw_uncommitted_source = False

    async def fetch(self, request: FetchRequest) -> FetchResult:
        self.saw_uncommitted_source = (
            self.repository.source_by_url("I-prepared", str(request.url)) is None
        )
        return FetchResult(
            final_url=request.url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body><p>Official finding.</p></body></html>",
            fetched_at=NOW,
        )


def seed(
    repository: InvestigationRepository, engine: Engine, run_id: str, mode: RunMode
) -> HarnessStore:
    try:
        repository.get(Investigation, "I-prepared")
    except KeyError:
        repository.add(
            Investigation(
                investigation_id="I-prepared",
                title="Prepared acquisition",
                event_description="A public event",
                investigation_goal="Atomic source acquisition",
                scope=InvestigationScope(summary="official records"),
                created_at=NOW,
                updated_at=NOW,
            )
        )
    repository.add(
        InvestigationRun(
            run_id=run_id,
            investigation_id="I-prepared",
            mode=mode,
            status=RunStatus.CREATED,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="acquisition-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store = HarnessStore(create_session_factory(engine), repository, clock=lambda: NOW)
    store.install_budget(
        RunBudget(
            run_id=run_id,
            max_research_rounds=2,
            max_search_calls=4,
            max_fetch_calls=4,
            max_model_calls=4,
            max_tokens=100,
            max_wall_time_ms=10_000,
            updated_at=NOW,
        )
    )
    return store


@pytest.mark.asyncio
async def test_prepared_acquisition_joins_step_commit_and_reuses_source_identity(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    fetch = FetchFixture(repository)
    service = SourceAcquisitionService(
        repository=repository,
        blobs=blobs,
        search=SearchFixture(),
        fetch=fetch,
        parsers=DocumentParserRegistry.default(),
        clock=lambda: NOW,
    )
    live_store = seed(repository, engine, "RUN-prepared-live", RunMode.LIVE)
    request = AcquisitionRequest(
        investigation_id="I-prepared",
        run_id="RUN-prepared-live",
        query="official report",
        max_results=1,
    )
    first = await service.prepare(request, logical_step_key="research:T1:round-1")
    second = await service.prepare(request, logical_step_key="research:T1:round-1")
    assert first.result == second.result
    assert [type(item) for item in first.business_outputs] == [
        type(item) for item in second.business_outputs
    ]
    assert fetch.saw_uncommitted_source
    assert repository.source_by_url("I-prepared", "https://agency.example/report") is None
    source_id = first.result.sources[0].source_id
    snapshot_id = first.result.sources[0].snapshot_id
    assert snapshot_id is not None
    with pytest.raises(KeyError):
        repository.get(SourceSnapshot, snapshot_id)

    step = live_store.begin_step(
        run_id=request.run_id,
        logical_step_key="research:T1:round-1",
        input_fingerprint=hashlib.sha256(b"prepared-live").hexdigest(),
        workflow_version="acquisition-v1",
        phase=WorkflowPhase.COLLECT,
        step_type=StepType.RESEARCH,
        agent_role=AgentRole.RESEARCHER,
        owner_instance_id="worker",
        research_round=1,
    )
    result_blob = blobs.put_bytes(first.result.model_dump_json().encode())
    assert blobs.verify_hash(result_blob.ref)
    live_store.complete_step(
        step_id=step.step_id,
        owner_instance_id="worker",
        elapsed_ms=50,
        output_refs=(result_blob.ref.uri,),
        output_schema_version="AcquisitionResult",
        business_outputs=first.business_outputs,
        route=Route.ANALYZE,
    )
    assert repository.get(Source, source_id).source_id == source_id
    live_snapshot = repository.get(SourceSnapshot, snapshot_id)

    replay_store = seed(repository, engine, "RUN-prepared-replay", RunMode.REPLAY)
    replay_request = request.model_copy(update={"run_id": "RUN-prepared-replay"})
    replay = await service.prepare(replay_request, logical_step_key="research:T1:round-1")
    assert replay.result.sources[0].source_id == source_id
    assert replay.result.sources[0].snapshot_id != snapshot_id
    assert all(not isinstance(item, Source) for item in replay.business_outputs)
    replay_step = replay_store.begin_step(
        run_id=replay_request.run_id,
        logical_step_key="research:T1:round-1",
        input_fingerprint=hashlib.sha256(b"prepared-replay").hexdigest(),
        workflow_version="acquisition-v1",
        phase=WorkflowPhase.COLLECT,
        step_type=StepType.RESEARCH,
        agent_role=AgentRole.RESEARCHER,
        owner_instance_id="replay-worker",
        research_round=1,
    )
    replay_blob = blobs.put_bytes(replay.result.model_dump_json().encode())
    replay_store.complete_step(
        step_id=replay_step.step_id,
        owner_instance_id="replay-worker",
        elapsed_ms=30,
        output_refs=(replay_blob.ref.uri,),
        output_schema_version="AcquisitionResult",
        business_outputs=replay.business_outputs,
        route=Route.ANALYZE,
    )
    replay_snapshot_id = replay.result.sources[0].snapshot_id
    assert replay_snapshot_id is not None
    replay_snapshot = repository.get(SourceSnapshot, replay_snapshot_id)
    assert replay_snapshot.raw_sha256 == live_snapshot.raw_sha256
