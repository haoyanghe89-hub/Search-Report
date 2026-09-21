from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    AnalysisProposal,
    PlanInput,
    PlanProposal,
    QuestionView,
    ResearchInput,
    ResearchProposal,
    TaskProposal,
    VerificationInput,
    VerificationProposal,
    WriterProposal,
)
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    ResearchTaskStatus,
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
    ResearchTask,
    RunBudget,
)
from marketpulse.investigation.harness.persistence import HarnessConflictError, HarnessStore
from marketpulse.investigation.harness.runtime import InvestigationHarness, StepOutcome
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.persistence.base import create_session_factory
from marketpulse.investigation.persistence.models import (
    ExecutionStepRow,
    InvestigationRunRow,
    ResearchTaskRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def seed(
    repository: InvestigationRepository,
    engine: Engine,
    *,
    suffix: str,
    phase: WorkflowPhase = WorkflowPhase.PLAN,
    clock: FakeClock | None = None,
) -> tuple[str, HarnessStore]:
    investigation_id = f"I-{suffix}"
    run_id = f"RUN-{suffix}"
    repository.add(
        Investigation(
            investigation_id=investigation_id,
            title="Harness test",
            event_description="A public event",
            investigation_goal="Test deterministic contracts",
            scope=InvestigationScope(summary="public sources"),
            created_at=NOW,
            updated_at=NOW,
        )
    )
    repository.add(
        InvestigationRun(
            run_id=run_id,
            investigation_id=investigation_id,
            mode=RunMode.LIVE,
            status=RunStatus.CREATED,
            current_phase=phase,
            checkpoint_version=0,
            state_version=0,
            workflow_version="harness-v1",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    sessions = create_session_factory(engine)
    store = HarnessStore(sessions, repository, clock=clock or FakeClock())
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
    return run_id, store


def test_step_identity_and_budget_roundtrip(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    run_id, store = seed(repository, engine, suffix="identity")
    fingerprint = hashlib.sha256(b"same semantic input").hexdigest()
    for key in ("research:T-1:round-1", "research:T-2:round-1"):
        repository.add(
            ExecutionStep(
                step_id=f"STEP-{key}",
                run_id=run_id,
                step_type=StepType.RESEARCH,
                agent_role=AgentRole.RESEARCHER,
                status=ExecutionStepStatus.PENDING,
                attempt=1,
                input_fingerprint=fingerprint,
                logical_step_key=key,
            )
        )
    assert len(store.repository.steps_for_run(create_session_factory(engine)(), run_id)) == 2
    assert store.read_budget(run_id).search_calls_used == 0
    with pytest.raises(IntegrityError):
        repository.add(
            ExecutionStep(
                step_id="STEP-duplicate",
                run_id=run_id,
                step_type=StepType.RESEARCH,
                agent_role=AgentRole.RESEARCHER,
                status=ExecutionStepStatus.PENDING,
                attempt=1,
                input_fingerprint=hashlib.sha256(b"other input").hexdigest(),
                logical_step_key="research:T-1:round-1",
            )
        )


def test_stale_owner_resume_excludes_downtime_and_reuses_completed_step(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    clock = FakeClock()
    run_id, store = seed(repository, engine, suffix="resume", clock=clock)
    fingerprint = hashlib.sha256(b"plan").hexdigest()
    kwargs = dict(
        run_id=run_id,
        logical_step_key="planning:initial",
        input_fingerprint=fingerprint,
        workflow_version="harness-v1",
        phase=WorkflowPhase.PLAN,
        step_type=StepType.PLANNING,
        agent_role=AgentRole.SUPERVISOR,
    )
    first = store.begin_step(**kwargs, owner_instance_id="worker-a")
    store.heartbeat(first.step_id, "worker-a", 1200)
    with pytest.raises(HarnessConflictError, match="active owner"):
        store.begin_step(**kwargs, owner_instance_id="worker-b")
    clock.advance(40)
    second = store.begin_step(**kwargs, owner_instance_id="worker-b")
    assert second.attempt == 2
    assert repository.get(ExecutionStep, first.step_id).status is ExecutionStepStatus.INTERRUPTED
    assert store.read_budget(run_id).consumed_wall_time_ms == 1200
    store.complete_step(
        step_id=second.step_id,
        owner_instance_id="worker-b",
        elapsed_ms=300,
        output_refs=("blob://sha256/" + fingerprint,),
        output_schema_version="PlanProposal",
        business_outputs=(),
        route=Route.COLLECT,
    )
    assert store.read_budget(run_id).consumed_wall_time_ms == 1500
    assert store.begin_step(**kwargs, owner_instance_id="worker-c").step_id == second.step_id
    with pytest.raises(Exception, match="logical Step input changed"):
        store.begin_step(
            **{**kwargs, "input_fingerprint": hashlib.sha256(b"changed").hexdigest()},
            owner_instance_id="worker-c",
        )
    run = repository.get(InvestigationRun, run_id)
    assert run.status is RunStatus.RUNNING
    assert run.last_completed_step_key == "planning:initial"
    assert run.current_phase is WorkflowPhase.COLLECT


def test_completion_rolls_back_outputs_step_and_checkpoint(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    repository, engine, _ = investigation_store
    run_id, store = seed(repository, engine, suffix="rollback")
    step = store.begin_step(
        run_id=run_id,
        logical_step_key="planning:initial",
        input_fingerprint=hashlib.sha256(b"plan").hexdigest(),
        workflow_version="harness-v1",
        phase=WorkflowPhase.PLAN,
        step_type=StepType.PLANNING,
        agent_role=AgentRole.SUPERVISOR,
        owner_instance_id="worker",
    )
    before = repository.get(InvestigationRun, run_id)
    invalid_task = ResearchTask(
        task_id="T-invalid",
        investigation_id="I-missing",
        run_id=run_id,
        title="Invalid task",
        objective="FK rollback probe",
        status=ResearchTaskStatus.PENDING,
        priority=1,
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(IntegrityError):
        store.complete_step(
            step_id=step.step_id,
            owner_instance_id="worker",
            elapsed_ms=100,
            output_refs=(),
            output_schema_version="PlanProposal",
            business_outputs=(invalid_task,),
            route=Route.COLLECT,
        )
    after = repository.get(InvestigationRun, run_id)
    assert after.checkpoint_version == before.checkpoint_version
    assert after.state_version == before.state_version
    assert repository.get(ExecutionStep, step.step_id).status is ExecutionStepStatus.RUNNING
    with create_session_factory(engine)() as session:
        assert (
            session.scalar(select(ResearchTaskRow).where(ResearchTaskRow.task_id == "T-invalid"))
            is None
        )


@pytest.mark.asyncio
async def test_fake_mainline_stops_at_ready_for_report(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    run_id, store = seed(repository, engine, suffix="mainline")
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    tick = [0.0]

    def monotonic() -> float:
        tick[0] += 0.2
        return tick[0]

    harness = InvestigationHarness(store, blobs, monotonic=monotonic)
    question = QuestionView(question_key="Q1", text="What happened?", is_critical=True)
    task = TaskProposal(
        task_key="T1", target_question_key="Q1", objective="Find records", priority=90
    )
    plan_input = PlanInput(
        case_key="case-1",
        scope_summary="public sources",
        questions=(question,),
        max_research_rounds=2,
    )
    plan = PlanProposal(tasks=(task,))

    async def plan_handler() -> StepOutcome:
        return StepOutcome(proposal=plan, route=Route.COLLECT)

    await harness.run_step(
        run_id=run_id,
        logical_step_key="planning:initial",
        workflow_version="harness-v1",
        phase=WorkflowPhase.PLAN,
        step_type=StepType.PLANNING,
        agent_role=AgentRole.SUPERVISOR,
        owner_instance_id="worker",
        semantic_input=plan_input,
        output_model=PlanProposal,
        handler=plan_handler,
    )
    research_input = ResearchInput(task=task, remaining_search_calls=4)

    async def research_handler() -> StepOutcome:
        return StepOutcome(proposal=ResearchProposal(queries=()), route=Route.ANALYZE)

    await harness.run_step(
        run_id=run_id,
        logical_step_key="research:T1:round-1",
        workflow_version="harness-v1",
        phase=WorkflowPhase.COLLECT,
        step_type=StepType.RESEARCH,
        agent_role=AgentRole.RESEARCHER,
        owner_instance_id="worker",
        semantic_input=research_input,
        output_model=ResearchProposal,
        handler=research_handler,
        dependency_keys=("planning:initial",),
        research_round=1,
    )
    analysis_input = AnalysisInput(artifacts=())

    async def analysis_handler() -> StepOutcome:
        return StepOutcome(proposal=AnalysisProposal(), route=Route.VERIFY)

    await harness.run_step(
        run_id=run_id,
        logical_step_key="analysis:round-1",
        workflow_version="harness-v1",
        phase=WorkflowPhase.ANALYZE,
        step_type=StepType.ANALYSIS,
        agent_role=AgentRole.ANALYST,
        owner_instance_id="worker",
        semantic_input=analysis_input,
        output_model=AnalysisProposal,
        handler=analysis_handler,
        dependency_keys=("research:T1:round-1",),
    )
    assert repository.get(InvestigationRun, run_id).status is RunStatus.VERIFYING
    verify_input = VerificationInput(claims=(), evidence=())

    async def verify_handler() -> StepOutcome:
        return StepOutcome(proposal=VerificationProposal(), route=Route.READY_FOR_REPORT)

    await harness.run_step(
        run_id=run_id,
        logical_step_key="verify:round-1",
        workflow_version="harness-v1",
        phase=WorkflowPhase.VERIFY,
        step_type=StepType.VALIDATION,
        agent_role=AgentRole.VERIFIER,
        owner_instance_id="worker",
        semantic_input=verify_input,
        output_model=VerificationProposal,
        handler=verify_handler,
        dependency_keys=("analysis:round-1",),
    )
    run = repository.get(InvestigationRun, run_id)
    assert run.status is RunStatus.READY_FOR_REPORT
    assert run.current_phase is WorkflowPhase.REPORT
    with create_session_factory(engine)() as session:
        assert session.scalar(
            select(InvestigationRunRow).where(InvestigationRunRow.run_id == run_id)
        )
        assert session.scalar(select(ExecutionStepRow).where(ExecutionStepRow.run_id == run_id))
        from marketpulse.investigation.persistence.models import ReportRow

        assert session.scalar(select(ReportRow).where(ReportRow.run_id == run_id)) is None
    with pytest.raises(ValidationError):
        WriterProposal.model_validate({"sections": [], "release_status": "PUBLISHED"})


def test_two_workers_race_for_one_step(
    investigation_store: tuple[InvestigationRepository, Engine, str],
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    repository, engine, _ = investigation_store
    run_id, store = seed(repository, engine, suffix="race")
    barrier = Barrier(3)
    fingerprint = hashlib.sha256(b"race").hexdigest()

    def claim(owner: str) -> str:
        barrier.wait()
        try:
            store.begin_step(
                run_id=run_id,
                logical_step_key="planning:initial",
                input_fingerprint=fingerprint,
                workflow_version="harness-v1",
                phase=WorkflowPhase.PLAN,
                step_type=StepType.PLANNING,
                agent_role=AgentRole.SUPERVISOR,
                owner_instance_id=owner,
            )
        except HarnessConflictError:
            return "conflict"
        return "won"

    with ThreadPoolExecutor(max_workers=2) as executor:
        left = executor.submit(claim, "worker-a")
        right = executor.submit(claim, "worker-b")
        barrier.wait()
        results = [left.result(), right.result()]
    assert sorted(results) == ["conflict", "won"]
    with create_session_factory(engine)() as session:
        steps = session.scalars(
            select(ExecutionStepRow).where(ExecutionStepRow.run_id == run_id)
        ).all()
    assert len(steps) == 1


@pytest.mark.asyncio
async def test_invalid_agent_reference_fails_step_and_network_runs_after_begin_commit(
    investigation_store: tuple[InvestigationRepository, Engine, str],
    tmp_path: Path,
) -> None:
    repository, engine, _ = investigation_store
    run_id, store = seed(repository, engine, suffix="invalid")
    blobs = LocalContentAddressedBlobStorage(tmp_path / "invalid-blobs")
    tick = [0.0]

    def monotonic() -> float:
        tick[0] += 0.1
        return tick[0]

    harness = InvestigationHarness(store, blobs, monotonic=monotonic)
    request = PlanInput(
        case_key="case-1",
        scope_summary="public event",
        questions=(QuestionView(question_key="Q1", text="What happened?", is_critical=True),),
        max_research_rounds=2,
    )

    async def invalid_handler() -> StepOutcome:
        with create_session_factory(engine)() as session:
            visible = session.scalar(
                select(ExecutionStepRow).where(ExecutionStepRow.run_id == run_id)
            )
            assert visible is not None
            assert visible.status is ExecutionStepStatus.RUNNING
        proposal = PlanProposal(
            tasks=(
                TaskProposal(
                    task_key="T1",
                    target_question_key="UNKNOWN",
                    objective="Invalid reference",
                    priority=80,
                ),
            )
        )
        return StepOutcome(proposal=proposal, route=Route.COLLECT)

    with pytest.raises(ValueError, match="unknown questions"):
        await harness.run_step(
            run_id=run_id,
            logical_step_key="planning:initial",
            workflow_version="harness-v1",
            phase=WorkflowPhase.PLAN,
            step_type=StepType.PLANNING,
            agent_role=AgentRole.SUPERVISOR,
            owner_instance_id="worker",
            semantic_input=request,
            output_model=PlanProposal,
            handler=invalid_handler,
        )
    run = repository.get(InvestigationRun, run_id)
    assert run.status is RunStatus.FAILED
    assert run.last_completed_step_key is None
    assert store.read_budget(run_id).consumed_wall_time_ms > 0
    from marketpulse.investigation.harness.runtime import semantic_fingerprint

    with pytest.raises(HarnessConflictError, match="not retryable"):
        store.begin_step(
            run_id=run_id,
            logical_step_key="planning:initial",
            input_fingerprint=semantic_fingerprint(request, workflow_version="harness-v1"),
            workflow_version="harness-v1",
            phase=WorkflowPhase.PLAN,
            step_type=StepType.PLANNING,
            agent_role=AgentRole.SUPERVISOR,
            owner_instance_id="worker-2",
        )
