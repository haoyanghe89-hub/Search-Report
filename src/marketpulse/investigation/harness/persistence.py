from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    RunStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import ExecutionStep, RunBudget
from marketpulse.investigation.harness.state_machine import (
    Route,
    phase_for,
    require_route,
    status_for,
)
from marketpulse.investigation.harness.uow import UnitOfWork
from marketpulse.investigation.persistence.models import (
    ExecutionStepRow,
    InvestigationRunRow,
    RunBudgetRow,
)
from marketpulse.investigation.persistence.repositories import (
    InvestigationRepository,
    PersistedEntity,
)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class HarnessConflictError(RuntimeError):
    code = "HARNESS_CONFLICT"


class ResumeVersionMismatchError(RuntimeError):
    code = "RESUME_VERSION_MISMATCH"


class RunBudgetExceededError(RuntimeError):
    code = "RUN_BUDGET_EXCEEDED"


class HarnessStore:
    """Short transactions for Step ownership, completion, and budget accounting."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
        *,
        clock: Clock = utc_now,
        stale_after: timedelta = timedelta(seconds=30),
    ) -> None:
        self.sessions = sessions
        self.repository = repository
        self.clock = clock
        self.stale_after = stale_after

    def install_budget(self, budget: RunBudget) -> None:
        with UnitOfWork(self.sessions, self.repository) as work:
            work.add(budget)
            work.commit()

    def read_budget(self, run_id: str) -> RunBudget:
        return self.repository.get(RunBudget, run_id)

    def begin_step(
        self,
        *,
        run_id: str,
        logical_step_key: str,
        input_fingerprint: str,
        workflow_version: str,
        phase: WorkflowPhase,
        step_type: StepType,
        agent_role: AgentRole,
        owner_instance_id: str,
        dependency_keys: tuple[str, ...] = (),
        research_round: int = 0,
    ) -> ExecutionStep:
        now = self.clock()
        with UnitOfWork(self.sessions, self.repository) as work:
            session = work.session
            run = session.get(InvestigationRunRow, run_id)
            budget = session.get(RunBudgetRow, run_id)
            if run is None or budget is None:
                raise KeyError(run_id)
            if run.workflow_version != workflow_version:
                raise ResumeVersionMismatchError("workflow version changed")
            previous = session.scalar(
                select(ExecutionStepRow)
                .where(
                    ExecutionStepRow.run_id == run_id,
                    ExecutionStepRow.logical_step_key == logical_step_key,
                )
                .order_by(desc(ExecutionStepRow.attempt))
            )
            if previous is not None:
                if previous.input_fingerprint != input_fingerprint:
                    raise ResumeVersionMismatchError("logical Step input changed")
                if previous.status is ExecutionStepStatus.COMPLETED:
                    return self.repository.get_in_session(session, ExecutionStep, previous.step_id)
                if previous.status is ExecutionStepStatus.FAILED and not previous.retryable:
                    raise HarnessConflictError("failed Step is not retryable")
                if previous.status in {
                    ExecutionStepStatus.CANCELLED,
                    ExecutionStepStatus.PENDING,
                }:
                    raise HarnessConflictError("Step cannot be continued")
            if run.current_phase is not phase:
                raise HarnessConflictError(
                    f"expected phase {phase.value}, found {run.current_phase.value}"
                )
            for key in dependency_keys:
                completed = session.scalar(
                    select(ExecutionStepRow.step_id).where(
                        ExecutionStepRow.run_id == run_id,
                        ExecutionStepRow.logical_step_key == key,
                        ExecutionStepRow.status == ExecutionStepStatus.COMPLETED,
                    )
                )
                if completed is None:
                    raise HarnessConflictError(f"dependency is not completed: {key}")
            old_owner = run.owner_instance_id
            old_heartbeat = run.owner_heartbeat_at
            if old_owner is not None:
                if old_owner == owner_instance_id:
                    raise HarnessConflictError("owner already has a running Step")
                if run.current_step_key != logical_step_key:
                    raise HarnessConflictError("stale owner belongs to another Step")
                heartbeat_utc = (
                    old_heartbeat.replace(tzinfo=UTC)
                    if old_heartbeat is not None and old_heartbeat.tzinfo is None
                    else old_heartbeat
                )
                if heartbeat_utc is None or now - heartbeat_utc < self.stale_after:
                    raise HarnessConflictError("Run has an active owner")
            if budget.consumed_wall_time_ms >= budget.max_wall_time_ms:
                raise RunBudgetExceededError("Run active-time budget exhausted")
            if research_round > budget.research_rounds_used:
                if research_round > budget.max_research_rounds:
                    raise RunBudgetExceededError("research round budget exhausted")
                budget.research_rounds_used = research_round
                budget.updated_at = now
            if previous is not None and previous.status is ExecutionStepStatus.RUNNING:
                previous.status = ExecutionStepStatus.INTERRUPTED
                previous.completed_at = now
                previous.error_code = "STALE_OWNER"
                previous.retryable = True
            result = session.execute(
                update(InvestigationRunRow)
                .where(
                    InvestigationRunRow.run_id == run_id,
                    InvestigationRunRow.state_version == run.state_version,
                    InvestigationRunRow.owner_instance_id == old_owner,
                    InvestigationRunRow.owner_heartbeat_at == old_heartbeat,
                )
                .values(
                    owner_instance_id=owner_instance_id,
                    owner_heartbeat_at=now,
                    current_step_key=logical_step_key,
                    current_phase=phase,
                    status=(
                        RunStatus.VERIFYING if phase is WorkflowPhase.VERIFY else RunStatus.RUNNING
                    ),
                    state_version=run.state_version + 1,
                    checkpoint_version=run.checkpoint_version + 1,
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", None) != 1:
                raise HarnessConflictError("Run ownership changed")
            step = ExecutionStep(
                step_id=f"STEP-{uuid.uuid4().hex}",
                run_id=run_id,
                step_type=step_type,
                agent_role=agent_role,
                status=ExecutionStepStatus.RUNNING,
                attempt=previous.attempt + 1 if previous is not None else 1,
                input_fingerprint=input_fingerprint,
                executor_instance_id=owner_instance_id,
                started_at=now,
                heartbeat_at=now,
                logical_step_key=logical_step_key,
                dependency_keys=dependency_keys,
            )
            work.add(step)
            work.commit()
            return step

    def _accrue(
        self, session: Session, step: ExecutionStepRow, elapsed_ms: int, now: datetime
    ) -> None:
        if elapsed_ms < step.active_elapsed_ms:
            raise ValueError("monotonic elapsed duration went backwards")
        delta = elapsed_ms - step.active_elapsed_ms
        budget = session.get(RunBudgetRow, step.run_id)
        if budget is None:
            raise KeyError(step.run_id)
        budget.consumed_wall_time_ms += delta
        budget.updated_at = now
        step.active_elapsed_ms = elapsed_ms
        step.heartbeat_at = now

    def heartbeat(self, step_id: str, owner_instance_id: str, elapsed_ms: int) -> None:
        now = self.clock()
        with UnitOfWork(self.sessions, self.repository) as work:
            step = work.session.get(ExecutionStepRow, step_id)
            if step is None:
                raise KeyError(step_id)
            run = work.session.get(InvestigationRunRow, step.run_id)
            if run is None or run.owner_instance_id != owner_instance_id:
                raise HarnessConflictError("Step owner changed")
            if step.status is not ExecutionStepStatus.RUNNING:
                raise HarnessConflictError("Step is not running")
            result = work.session.execute(
                update(InvestigationRunRow)
                .where(
                    InvestigationRunRow.run_id == run.run_id,
                    InvestigationRunRow.owner_instance_id == owner_instance_id,
                    InvestigationRunRow.owner_heartbeat_at == run.owner_heartbeat_at,
                    InvestigationRunRow.current_step_key == step.logical_step_key,
                )
                .values(owner_heartbeat_at=now, updated_at=now)
            )
            if getattr(result, "rowcount", None) != 1:
                raise HarnessConflictError("Step owner changed during heartbeat")
            self._accrue(work.session, step, elapsed_ms, now)
            work.commit()

    def complete_step(
        self,
        *,
        step_id: str,
        owner_instance_id: str,
        elapsed_ms: int,
        output_refs: tuple[str, ...],
        output_schema_version: str,
        business_outputs: tuple[PersistedEntity, ...],
        route: Route,
    ) -> ExecutionStep:
        now = self.clock()
        with UnitOfWork(self.sessions, self.repository) as work:
            session = work.session
            step = session.get(ExecutionStepRow, step_id)
            if step is None:
                raise KeyError(step_id)
            run = session.get(InvestigationRunRow, step.run_id)
            if (
                run is None
                or run.owner_instance_id != owner_instance_id
                or run.current_step_key != step.logical_step_key
                or step.status is not ExecutionStepStatus.RUNNING
            ):
                raise HarnessConflictError("Step completion lost ownership")
            require_route(run.current_phase, route)
            self._accrue(session, step, elapsed_ms, now)
            for entity in business_outputs:
                work.add(entity)
            step.output_refs = list(output_refs)
            step.output_schema_version = output_schema_version
            step.status = ExecutionStepStatus.COMPLETED
            step.completed_at = now
            result = session.execute(
                update(InvestigationRunRow)
                .where(
                    InvestigationRunRow.run_id == run.run_id,
                    InvestigationRunRow.state_version == run.state_version,
                    InvestigationRunRow.owner_instance_id == owner_instance_id,
                )
                .values(
                    owner_instance_id=None,
                    owner_heartbeat_at=None,
                    current_step_key=None,
                    last_completed_step_key=step.logical_step_key,
                    current_phase=phase_for(route),
                    status=status_for(route),
                    state_version=run.state_version + 1,
                    checkpoint_version=run.checkpoint_version + 1,
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", None) != 1:
                raise HarnessConflictError("Run changed during completion")
            session.flush()
            completed = self.repository.get_in_session(session, ExecutionStep, step_id)
            work.commit()
            return completed

    def fail_step(
        self,
        *,
        step_id: str,
        owner_instance_id: str,
        elapsed_ms: int,
        error_code: str,
        retryable: bool,
        interrupted: bool = False,
    ) -> None:
        now = self.clock()
        with UnitOfWork(self.sessions, self.repository) as work:
            session = work.session
            step = session.get(ExecutionStepRow, step_id)
            if step is None:
                raise KeyError(step_id)
            run = session.get(InvestigationRunRow, step.run_id)
            if (
                run is None
                or run.owner_instance_id != owner_instance_id
                or step.status is not ExecutionStepStatus.RUNNING
            ):
                raise HarnessConflictError("Step failure lost ownership")
            self._accrue(session, step, elapsed_ms, now)
            step.status = (
                ExecutionStepStatus.INTERRUPTED if interrupted else ExecutionStepStatus.FAILED
            )
            step.completed_at = now
            step.error_code = error_code
            step.retryable = retryable
            run.status = RunStatus.INTERRUPTED if interrupted else RunStatus.FAILED
            run.owner_instance_id = None
            run.owner_heartbeat_at = None
            run.current_step_key = step.logical_step_key
            run.interruption_reason = error_code
            run.checkpoint_version += 1
            run.state_version += 1
            run.updated_at = now
            work.commit()
