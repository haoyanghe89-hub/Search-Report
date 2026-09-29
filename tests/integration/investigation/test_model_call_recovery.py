from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

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
    ExecutionStep,
    Investigation,
    InvestigationRun,
    InvestigationScope,
    RunBudget,
)
from marketpulse.investigation.harness.calls import BoundExternalCalls, StepCallSite
from marketpulse.investigation.harness.model_call_journal import ModelCallOutcomeUnknownError
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.ports.external import (
    ModelMessage,
    ModelRequest,
    ModelUsage,
    StructuredModelResult,
)
from marketpulse.investigation.recording.errors import (
    InvalidProviderResponseError,
    ReplayCacheMissError,
)
from marketpulse.investigation.recording.store import RepositoryRecordedCallStore

T = TypeVar("T", bound=BaseModel)


class Answer(BaseModel):
    text: str


class Model:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    async def generate(self, request: ModelRequest[T]) -> StructuredModelResult[T]:
        self.calls += 1
        if self.error:
            raise self.error
        return StructuredModelResult(
            output=request.response_model.model_validate({"text": "archived answer"}),
            provider="fixture",
            model="fixture-v1",
            usage=ModelUsage(input_tokens=3, output_tokens=2),
        )


@pytest.fixture
def recovery(
    investigation_store: tuple[InvestigationRepository, Engine, str], tmp_path: Path
) -> tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model]:
    repository, engine, _ = investigation_store
    now = datetime.now(UTC)
    repository.add(
        Investigation(
            investigation_id="I-recovery",
            title="Recovery",
            event_description="A fixture",
            investigation_goal="Recover model calls",
            scope=InvestigationScope(summary="test"),
            created_at=now,
            updated_at=now,
        )
    )
    repository.add(
        InvestigationRun(
            run_id="R-recovery",
            investigation_id="I-recovery",
            mode=RunMode.LIVE,
            status=RunStatus.RUNNING,
            current_phase=WorkflowPhase.PLAN,
            checkpoint_version=0,
            state_version=0,
            workflow_version="test-v1",
            created_at=now,
            updated_at=now,
        )
    )
    repository.add(
        ExecutionStep(
            step_id="S-recovery",
            run_id="R-recovery",
            step_type=StepType.PLANNING,
            agent_role=AgentRole.SUPERVISOR,
            status=ExecutionStepStatus.RUNNING,
            attempt=1,
            input_fingerprint="a" * 64,
            logical_step_key="plan",
        )
    )
    repository.add(
        RunBudget(
            run_id="R-recovery",
            max_research_rounds=2,
            max_search_calls=4,
            max_fetch_calls=4,
            max_model_calls=4,
            max_tokens=100,
            max_wall_time_ms=10000,
            updated_at=now,
        )
    )
    model = Model()
    calls = BoundExternalCalls(
        sessions=create_session_factory(engine),
        repository=repository,
        recordings=RepositoryRecordedCallStore(
            repository, LocalContentAddressedBlobStorage(tmp_path / "blobs")
        ),
        live_model=model,
    )
    request = ModelRequest[Answer](
        messages=(ModelMessage(role="user", content="answer"),),
        response_model=Answer,
        response_schema_version="answer-v1",
        prompt_version="prompt-v1",
    )
    return calls, StepCallSite("R-recovery", "S-recovery", "plan", "model", 0), request, model


async def test_provider_completed_but_record_save_crashed_blocks_automatic_retry(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, site, request, model = recovery
    original = calls.recordings.add_model_call

    def crash(*args: object) -> None:
        raise OSError("database unavailable after provider completion")

    monkeypatch.setattr(calls.recordings, "add_model_call", crash)
    with pytest.raises(OSError):
        await calls.model(site, request)
    monkeypatch.setattr(calls.recordings, "add_model_call", original)
    resumed = BoundExternalCalls(
        sessions=calls.sessions,
        repository=calls.repository,
        recordings=calls.recordings,
        live_model=model,
    )
    with pytest.raises(ModelCallOutcomeUnknownError, match="duplicate charges"):
        await resumed.model(site, request)
    assert model.calls == 1
    assert calls.repository.get(RunBudget, site.run_id).model_calls_used == 1
    assert len(calls.repository.list_audit_events("I-recovery")) == 1

    from marketpulse.investigation.evaluation.live import summarize_live_run

    metrics = summarize_live_run(calls.sessions, calls.recordings._blobs, site.run_id)
    assert metrics["unrecorded_model_reservations"] == 1
    assert metrics["cost"] is None
    assert metrics["human_review"]["conclusion_correctness"] is None

    result = await resumed.model(site, request, retry_unknown_outcome=True)
    assert result.output.text == "archived answer"
    assert model.calls == 2
    metrics = summarize_live_run(calls.sessions, calls.recordings._blobs, site.run_id)
    assert metrics["recorded_input_tokens"] == 3
    assert metrics["recorded_output_tokens"] == 2
    assert metrics["unrecorded_model_reservations"] == 1
    budget = calls.repository.get(RunBudget, site.run_id)
    assert budget.model_calls_used == 2
    assert budget.tokens_used == 5  # Unknown first-call usage is not invented.
    intents = calls.repository.list_audit_events("I-recovery")
    assert intents[-1].metadata["retry_policy"] == "ALLOW_POSSIBLE_DUPLICATE_CHARGE"
    assert intents[-1].metadata["retry_of_unknown_intent"] == intents[0].audit_event_id
    await resumed.model(site, request)
    assert model.calls == 2


async def test_saved_response_survives_crash_before_binding_without_another_charge(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, site, request, model = recovery
    original = calls._bind

    def crash(**kwargs: object) -> None:
        raise OSError("crash before binding")

    monkeypatch.setattr(calls, "_bind", crash)
    with pytest.raises(OSError):
        await calls.model(site, request)
    monkeypatch.setattr(calls, "_bind", original)
    result = await calls.model(site, request)
    assert result.output.text == "archived answer"
    assert model.calls == 1
    assert calls.repository.get(RunBudget, site.run_id).tokens_used == 5


async def test_timeout_is_uncertain_but_invalid_response_can_be_repaired(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
) -> None:
    calls, site, request, model = recovery
    model.error = InvalidProviderResponseError("bad JSON")
    with pytest.raises(InvalidProviderResponseError):
        await calls.model(site, request)
    model.error = TimeoutError("provider outcome unknown")
    with pytest.raises(TimeoutError):
        await calls.model(site, request)
    model.error = None
    with pytest.raises(ModelCallOutcomeUnknownError):
        await calls.model(site, request)
    assert model.calls == 2


async def test_replay_miss_with_live_model_and_retry_permission_still_fails_closed(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
) -> None:
    calls, site, request, model = recovery
    replay = BoundExternalCalls(
        sessions=calls.sessions,
        repository=calls.repository,
        recordings=calls.recordings,
        source_run_id="old-version-run",
        live_model=model,
    )
    with pytest.raises(ReplayCacheMissError):
        await replay.model(site, request, retry_unknown_outcome=True)
    assert model.calls == 0
    assert calls.repository.list_audit_events("I-recovery") == []


async def test_budget_failure_does_not_leave_a_false_unknown_intent(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
) -> None:
    calls, site, request, model = recovery
    from sqlalchemy import update

    from marketpulse.investigation.persistence.models import RunBudgetRow

    with calls.sessions.begin() as session:
        session.execute(update(RunBudgetRow).values(max_model_calls=0))
    with pytest.raises(RunBudgetExceededError):
        await calls.model(site, request)
    assert model.calls == 0
    assert calls.repository.list_audit_events("I-recovery") == []


def test_competing_dispatch_intents_cannot_both_reserve_budget(
    recovery: tuple[BoundExternalCalls, StepCallSite, ModelRequest[Answer], Model],
) -> None:
    from sqlalchemy.exc import IntegrityError

    from marketpulse.investigation.harness.model_call_journal import prepare_model_intent
    from marketpulse.investigation.recording.canonical import request_fingerprint

    calls, site, request, model = recovery
    arguments = dict(
        run_id=site.run_id,
        logical_step_key=site.logical_step_key,
        call_site_key=site.call_site_key,
        call_ordinal=site.call_ordinal,
        fingerprint=request_fingerprint("model.generate", request),
        next_record_attempt=1,
        retry_unknown_outcome=False,
    )
    first, _ = prepare_model_intent(calls.sessions, **arguments)
    competing, _ = prepare_model_intent(calls.sessions, **arguments)
    calls._reserve(site.run_id, "model.generate", intent=first)
    with pytest.raises(IntegrityError):
        calls._reserve(site.run_id, "model.generate", intent=competing)
    assert calls.repository.get(RunBudget, site.run_id).model_calls_used == 1
    assert model.calls == 0
