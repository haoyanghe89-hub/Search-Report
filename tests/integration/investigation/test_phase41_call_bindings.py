from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy import Engine

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
    CallBinding,
    ExecutionStep,
    Investigation,
    InvestigationRun,
    InvestigationScope,
    RunBudget,
)
from marketpulse.investigation.harness.calls import (
    BoundExternalCalls,
    ReplayBindingMismatchError,
    StepCallSite,
)
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    ModelMessage,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResult,
    StructuredModelResult,
)
from marketpulse.investigation.recording.canonical import request_fingerprint
from marketpulse.investigation.recording.errors import ReplayCacheMissError
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class FakeSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, request: SearchRequest) -> SearchResult:
        self.calls += 1
        return SearchResult(items=(), provider="fixture", retrieved_at=NOW)


class ModelOutput(BaseModel):
    conclusion: str


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self, request: ModelRequest[ModelOutput]
    ) -> StructuredModelResult[ModelOutput]:
        self.calls += 1
        return StructuredModelResult(
            output=ModelOutput(conclusion="candidate"),
            provider="fixture",
            model="fake",
            usage=ModelUsage(input_tokens=4, output_tokens=3),
        )


def seed(
    repository: InvestigationRepository,
    *,
    suffix: str,
    mode: RunMode = RunMode.LIVE,
) -> tuple[str, StepCallSite]:
    investigation_id = f"I-bind-{suffix}"
    run_id = f"RUN-bind-{suffix}"
    step_id = f"STEP-bind-{suffix}"
    repository.add(
        Investigation(
            investigation_id=investigation_id,
            title="Binding test",
            event_description="A public event",
            investigation_goal="Verify call identity",
            scope=InvestigationScope(summary="public sources"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id=run_id,
            investigation_id=investigation_id,
            mode=mode,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.COLLECT,
            checkpoint_version=0,
            state_version=0,
            workflow_version="harness-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        ExecutionStep(
            step_id=step_id,
            run_id=run_id,
            step_type=StepType.RESEARCH,
            agent_role=AgentRole.RESEARCHER,
            status=ExecutionStepStatus.RUNNING,
            attempt=1,
            input_fingerprint=hashlib.sha256(b"research").hexdigest(),
            logical_step_key="research:T-1:round-1",
        )
    )
    repository.add(
        RunBudget(
            run_id=run_id,
            max_research_rounds=2,
            max_search_calls=4,
            max_fetch_calls=4,
            max_model_calls=4,
            max_tokens=30,
            max_wall_time_ms=10_000,
            updated_at=NOW,
        )
    )
    return run_id, StepCallSite(
        run_id=run_id,
        step_id=step_id,
        logical_step_key="research:T-1:round-1",
        call_site_key="research.search.primary",
        call_ordinal=0,
    )


@pytest.mark.asyncio
async def test_binding_reuses_durable_live_call_and_replay_matches_site(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    sessions = create_session_factory(engine)
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    recordings = RepositoryRecordedCallStore(repository, blobs)
    live_run, primary = seed(repository, suffix="live")
    search = FakeSearch()
    live = BoundExternalCalls(
        sessions=sessions, repository=repository, recordings=recordings, live_search=search
    )
    request = SearchRequest(query="official report", config_version="runtime-v1")
    first = await live.search(primary, request)
    secondary = StepCallSite(
        run_id=primary.run_id,
        step_id=primary.step_id,
        logical_step_key=primary.logical_step_key,
        call_site_key="research.search.secondary",
        call_ordinal=0,
    )
    await live.search(secondary, request)
    assert search.calls == 2
    assert repository.get(RunBudget, live_run).search_calls_used == 2

    restarted = BoundExternalCalls(sessions=sessions, repository=repository, recordings=recordings)
    assert await restarted.search(primary, request) == first
    assert search.calls == 2
    assert repository.get(RunBudget, live_run).search_calls_used == 2
    with sessions() as session:
        primary_binding = repository.binding_for_site(
            session, live_run, primary.logical_step_key, primary.call_site_key, 0
        )
        secondary_binding = repository.binding_for_site(
            session, live_run, secondary.logical_step_key, secondary.call_site_key, 0
        )
    assert primary_binding is not None and secondary_binding is not None
    assert primary_binding.recorded_call_id != secondary_binding.recorded_call_id
    assert repository.get(CallBinding, primary_binding.binding_id) == primary_binding

    replay_run, replay_site = seed(repository, suffix="replay", mode=RunMode.REPLAY)
    replay = BoundExternalCalls(
        sessions=sessions,
        repository=repository,
        recordings=recordings,
        source_run_id=live_run,
    )
    assert await replay.search(replay_site, request) == first
    assert repository.get(RunBudget, replay_run).search_calls_used == 1
    assert search.calls == 2
    with pytest.raises(ReplayBindingMismatchError):
        await replay.search(
            replay_site,
            SearchRequest(query="official report", config_version="runtime-v2"),
        )
    missing_site = StepCallSite(
        run_id=replay_site.run_id,
        step_id=replay_site.step_id,
        logical_step_key=replay_site.logical_step_key,
        call_site_key="research.search.missing",
        call_ordinal=0,
    )
    with pytest.raises(ReplayCacheMissError):
        await replay.search(missing_site, request)


@pytest.mark.asyncio
async def test_model_binding_charges_tokens_once_and_checks_prompt_version(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    sessions = create_session_factory(engine)
    recordings = RepositoryRecordedCallStore(
        repository, LocalContentAddressedBlobStorage(tmp_path / "model-blobs")
    )
    run_id, site = seed(repository, suffix="model")
    model = FakeModel()
    live = BoundExternalCalls(
        sessions=sessions, repository=repository, recordings=recordings, live_model=model
    )
    model_site = StepCallSite(
        run_id=site.run_id,
        step_id=site.step_id,
        logical_step_key=site.logical_step_key,
        call_site_key="analyst.extract",
        call_ordinal=0,
    )
    request = ModelRequest[ModelOutput](
        messages=(ModelMessage(role="user", content="Extract candidate"),),
        response_model=ModelOutput,
        response_schema_version="1",
        prompt_version="p1",
    )
    assert (await live.model(model_site, request)).output.conclusion == "candidate"
    assert (await live.model(model_site, request)).output.conclusion == "candidate"
    assert model.calls == 1
    budget = repository.get(RunBudget, run_id)
    assert budget.model_calls_used == 1
    assert budget.tokens_used == 7

    replay_run, replay_site = seed(repository, suffix="model-replay", mode=RunMode.REPLAY)
    replay_model_site = StepCallSite(
        run_id=replay_site.run_id,
        step_id=replay_site.step_id,
        logical_step_key=replay_site.logical_step_key,
        call_site_key="analyst.extract",
        call_ordinal=0,
    )
    replay = BoundExternalCalls(
        sessions=sessions,
        repository=repository,
        recordings=recordings,
        source_run_id=run_id,
    )
    assert (await replay.model(replay_model_site, request)).output.conclusion == "candidate"
    assert repository.get(RunBudget, replay_run).tokens_used == 7
    with pytest.raises(ReplayBindingMismatchError):
        await replay.model(
            replay_model_site,
            request.model_copy(update={"prompt_version": "p2"}),
        )
    assert request_fingerprint("model.generate", request) != request_fingerprint(
        "model.generate", request.model_copy(update={"prompt_version": "p2"})
    )


@pytest.mark.asyncio
async def test_retry_recovers_recorded_call_before_binding_commit(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, engine, _ = investigation_store
    sessions = create_session_factory(engine)
    recordings = RepositoryRecordedCallStore(
        repository, LocalContentAddressedBlobStorage(tmp_path / "crash-blobs")
    )
    run_id, site = seed(repository, suffix="binding-crash")
    search = FakeSearch()
    live = BoundExternalCalls(
        sessions=sessions, repository=repository, recordings=recordings, live_search=search
    )
    request = SearchRequest(query="durable before binding")

    def crash_before_binding(**kwargs: object) -> None:
        raise RuntimeError("simulated process exit after recorded call commit")

    monkeypatch.setattr(live, "_bind", crash_before_binding)
    with pytest.raises(RuntimeError, match="simulated process exit"):
        await live.search(site, request)
    assert search.calls == 1
    with sessions() as session:
        assert (
            repository.binding_for_site(
                session, run_id, site.logical_step_key, site.call_site_key, 0
            )
            is None
        )
    recovered = BoundExternalCalls(sessions=sessions, repository=repository, recordings=recordings)
    assert (await recovered.search(site, request)).provider == "fixture"
    assert search.calls == 1
    assert repository.get(RunBudget, run_id).search_calls_used == 1
