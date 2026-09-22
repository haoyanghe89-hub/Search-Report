from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.agents.contracts import (
    AgentContract,
    VerificationProposal,
    route_for_verification,
    validate_agent_proposal,
)
from marketpulse.investigation.domain.enums import (
    AgentRole,
    ExecutionStepStatus,
    StepType,
    WorkflowPhase,
)
from marketpulse.investigation.domain.runtime import ExecutionStep
from marketpulse.investigation.harness.persistence import HarnessStore
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.harness.uow import TransactionOperation
from marketpulse.investigation.persistence.repositories import PersistedEntity

OutputT = TypeVar("OutputT", bound=BaseModel)
Notify = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class StepOutcome:
    proposal: BaseModel
    route: Route
    business_outputs: tuple[PersistedEntity, ...] = ()
    transaction_operations: tuple[TransactionOperation, ...] = ()


def semantic_fingerprint(value: BaseModel, *, workflow_version: str) -> str:
    payload = {
        "workflow_version": workflow_version,
        "semantic_input": value.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class InvestigationHarness:
    """Executes one typed Step; network/model work is outside any DB transaction."""

    def __init__(
        self,
        store: HarnessStore,
        blobs: BlobStoragePort,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        heartbeat_interval_seconds: float = 1.0,
        notify: Notify | None = None,
    ) -> None:
        self.store = store
        self.blobs = blobs
        self.monotonic = monotonic
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.notify = notify

    async def _pulse(self, step_id: str, owner_id: str, started: float) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            elapsed_ms = max(0, int((self.monotonic() - started) * 1000))
            await asyncio.to_thread(self.store.heartbeat, step_id, owner_id, elapsed_ms)

    @staticmethod
    async def _stop_pulse(pulse: asyncio.Task[None]) -> None:
        pulse.cancel()
        try:
            await pulse
        except asyncio.CancelledError:
            pass

    async def run_step(
        self,
        *,
        run_id: str,
        logical_step_key: str,
        workflow_version: str,
        phase: WorkflowPhase,
        step_type: StepType,
        agent_role: AgentRole,
        owner_instance_id: str,
        semantic_input: BaseModel,
        output_model: type[OutputT],
        handler: Callable[[], Awaitable[StepOutcome]],
        on_step_started: Callable[[ExecutionStep], None] | None = None,
        dependency_keys: tuple[str, ...] = (),
        research_round: int = 0,
        timeout_seconds: float = 120.0,
    ) -> OutputT:
        if timeout_seconds <= 0:
            raise ValueError("Step timeout must be positive")
        fingerprint = semantic_fingerprint(semantic_input, workflow_version=workflow_version)
        step = self.store.begin_step(
            run_id=run_id,
            logical_step_key=logical_step_key,
            input_fingerprint=fingerprint,
            workflow_version=workflow_version,
            phase=phase,
            step_type=step_type,
            agent_role=agent_role,
            owner_instance_id=owner_instance_id,
            dependency_keys=dependency_keys,
            research_round=research_round,
        )
        if step.status is ExecutionStepStatus.COMPLETED:
            if step.output_schema_version != output_model.__name__ or not step.output_refs:
                raise ValueError("completed Step output schema or payload is missing")
            return output_model.model_validate_json(
                self.blobs.get_bytes(BlobRef.from_uri(step.output_refs[0]))
            )

        if on_step_started is not None:
            on_step_started(step)

        budget = self.store.read_budget(run_id)
        remaining_ms = max(1, budget.max_wall_time_ms - budget.consumed_wall_time_ms)
        effective_timeout = min(timeout_seconds, remaining_ms / 1000)
        started = self.monotonic()
        pulse = asyncio.create_task(self._pulse(step.step_id, owner_instance_id, started))
        try:
            outcome = await asyncio.wait_for(handler(), timeout=effective_timeout)
            proposal = output_model.model_validate(outcome.proposal)
            if isinstance(semantic_input, AgentContract) and isinstance(proposal, AgentContract):
                validate_agent_proposal(semantic_input, proposal)
            if isinstance(proposal, VerificationProposal):
                if outcome.route is not route_for_verification(proposal):
                    raise ValueError("Verifier gap routing disagrees with the proposal")
            stored = self.blobs.put_bytes(proposal.model_dump_json().encode("utf-8"))
            if not self.blobs.verify_hash(stored.ref):
                raise ValueError("Step output Blob failed verification")
            await self._stop_pulse(pulse)
            elapsed_ms = max(0, int((self.monotonic() - started) * 1000))
            self.store.complete_step(
                step_id=step.step_id,
                owner_instance_id=owner_instance_id,
                elapsed_ms=elapsed_ms,
                output_refs=(stored.ref.uri,),
                output_schema_version=output_model.__name__,
                business_outputs=outcome.business_outputs,
                transaction_operations=outcome.transaction_operations,
                route=outcome.route,
            )
        except BaseException as error:
            try:
                await self._stop_pulse(pulse)
            except BaseException:
                pass
            elapsed_ms = max(0, int((self.monotonic() - started) * 1000))
            try:
                self.store.fail_step(
                    step_id=step.step_id,
                    owner_instance_id=owner_instance_id,
                    elapsed_ms=elapsed_ms,
                    error_code=getattr(error, "code", type(error).__name__),
                    retryable=isinstance(error, (TimeoutError, ConnectionError)),
                    interrupted=isinstance(error, asyncio.CancelledError),
                )
            except Exception:
                pass
            raise
        if self.notify is not None:
            try:
                await self.notify(run_id, logical_step_key)
            except Exception:
                pass
        return proposal
