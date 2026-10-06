from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, TypeVar

from pydantic import BaseModel

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.agents.contracts import (
    CandidateRelation,
    ClaimCandidate,
    ClaimDecompositionInput,
    PlanProposal,
    ReportInput,
    RouteInput,
    RouteProposal,
    TaskProposal,
    VerificationInput,
    VerificationProposal,
    validate_agent_proposal,
)
from marketpulse.investigation.agents.contracts import (
    SemanticJudgment as AgentSemanticJudgment,
)
from marketpulse.investigation.agents.model_agents import (
    ModelAnalystAgent,
    ModelPlannerAgent,
    ModelResearcherAgent,
    ModelVerifierAgent,
)
from marketpulse.investigation.agents.supplements import supplemented_qualifiers
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ResearchGap,
    TimelineEvent,
)
from marketpulse.investigation.domain.enums import (
    AgentRole,
    AuditActorType,
    EntailmentStatus,
    ExecutionStepStatus,
    GapSeverity,
    GapStatus,
    RelationStance,
    ResearchGapType,
    ResearchTaskStatus,
    RunStatus,
    StepType,
    TimePrecision,
    ValidationStatus,
    WorkflowPhase,
)
from marketpulse.investigation.domain.reports import AuditEvent
from marketpulse.investigation.domain.runtime import ResearchTask
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.feedback.acquisition_batch import acquisition_batch
from marketpulse.investigation.feedback.context import (
    AgentContextBuilder,
    claim_key,
    publisher_state,
)
from marketpulse.investigation.feedback.guards import (
    ClaimGuard,
    EvidenceCreationGuard,
    ProposalGuardError,
    QueryGuard,
    normalize_query,
    stable_id,
)
from marketpulse.investigation.feedback.information_gain import (
    InformationGainCalculator,
    NoProgressDetector,
)
from marketpulse.investigation.feedback.models import (
    AnalysisExecutionResult,
    ClaimValidationSummary,
    FeedbackLoopConfig,
    FeedbackLoopResult,
    InformationGainSummary,
    PhaseTransition,
    ResearchExecutionResult,
    RoundSnapshot,
    VerificationExecutionResult,
)
from marketpulse.investigation.feedback.research_team import research_team
from marketpulse.investigation.feedback.semantic_reuse import reusable_judgments
from marketpulse.investigation.feedback.store import (
    CompleteResearchTaskOperation,
    FeedbackState,
    FeedbackStore,
    ReserveSourcesOperation,
    ResolveGapsOperation,
)
from marketpulse.investigation.feedback.supplements import PersistQualifierSupplementsOperation
from marketpulse.investigation.feedback.verification_team import verification_team
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.harness.checkpoints import (
    RESUMABLE_WORKFLOW_VERSION,
    StepInputCheckpoints,
    WorkerCheckpoint,
)
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.harness.runtime import InvestigationHarness, StepOutcome
from marketpulse.investigation.harness.scoped_ports import StepPortScope
from marketpulse.investigation.harness.stage_budget import (
    StageBudgetPolicy,
    VerificationBudgetPolicy,
)
from marketpulse.investigation.harness.state_machine import Route
from marketpulse.investigation.harness.uow import TransactionOperation
from marketpulse.investigation.ingestion.registry import DocumentParserRegistry
from marketpulse.investigation.persistence.repositories import (
    InvestigationRepository,
    PersistedEntity,
)
from marketpulse.investigation.recording.errors import InvalidProviderResponseError
from marketpulse.investigation.services.source_acquisition import (
    AcquisitionRequest,
    PreparedAcquisition,
    SourceAcquisitionService,
)
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.models import (
    ConflictObservation,
    SemanticJudgment,
    ValidationRequest,
)
from marketpulse.investigation.validation.persistence import PersistValidationOperation
from marketpulse.investigation.validation.policy import ValidationPolicy

Clock = Callable[[], datetime]
OutputT = TypeVar("OutputT", bound=BaseModel)


def _now() -> datetime:
    return datetime.now(UTC)


class AgentFeedbackOrchestrator:
    """Runs the first real persisted Agent feedback loop through Harness Steps."""

    @staticmethod
    async def run_quant(service, *, run_id, spec, inputs, instrument_id, asof, idempotency_key):
        """Opt-in frozen compute -> validation -> persisted v2 report material.

        The existing web 15-stage policy/calls/ordinals are not changed.
        """
        import asyncio

        from marketpulse.quant.reporting import build_material, persist_material

        job_id = await service.submit(
            run_id=run_id,
            spec=spec,
            inputs=inputs,
            instrument_id=instrument_id,
            asof=asof,
            idempotency_key=idempotency_key,
        )
        progress = getattr(service, "public_phase", None)
        if progress:
            progress(run_id, "证据核验", WorkflowPhase.VERIFY)
        material = await build_material(service, job_id=job_id)
        await asyncio.to_thread(
            persist_material, service.sessions, run_id=run_id, material=material
        )
        if progress:
            progress(run_id, "成稿", WorkflowPhase.REPORT)
        return job_id

    def __init__(
        self,
        *,
        harness: InvestigationHarness,
        calls: BoundExternalCalls,
        store: FeedbackStore,
        repository: InvestigationRepository,
        blobs: BlobStoragePort,
        parsers: DocumentParserRegistry,
        validation_policy: ValidationPolicy,
        integrity: EvidenceIntegrityValidator,
        owner_instance_id: str,
        config: FeedbackLoopConfig | None = None,
        clock: Clock = _now,
        progress: Callable[[str, str], None] | None = None,
    ) -> None:
        self.harness = harness
        self.calls = calls
        self.store = store
        self.repository = repository
        self.blobs = blobs
        self.parsers = parsers
        self.validation_policy = validation_policy
        self.integrity = integrity
        self.owner = owner_instance_id
        self.config = config or FeedbackLoopConfig()
        self.clock = clock
        self.context = AgentContextBuilder(store, blobs, self.config)
        self.gain = InformationGainCalculator()
        self.progress = progress
        self.checkpoints = StepInputCheckpoints(repository, blobs)
        self.stage_budget = StageBudgetPolicy(
            verify_tokens=self.config.verify_token_reserve_fraction,
            report_tokens=self.config.report_token_reserve_fraction,
            verify_calls=self.config.verify_call_reserve_fraction,
            report_calls=self.config.report_call_reserve_fraction,
        )

    def _pinned_input(self, run_id: str, logical_key: str, request: OutputT) -> OutputT:
        if self.config.workflow_version != RESUMABLE_WORKFLOW_VERSION:
            return request
        return self.checkpoints.pinned_input(
            run_id, logical_key, self.config.workflow_version, request
        )

    async def run(self, run_id: str) -> FeedbackLoopResult:
        trace: list[str] = []
        proposal_stop_reason: str | None = None
        gains: list[InformationGainSummary] = []
        no_progress = NoProgressDetector(self.config.no_progress_rounds)
        before_round: dict[int, RoundSnapshot] = {}

        state = self.store.state(run_id)
        if self.config.workflow_version == RESUMABLE_WORKFLOW_VERSION:
            before_round = {
                int(key.rsplit(":", 1)[-1]): value
                for key, value in self.checkpoints.saved_inputs(
                    self.store.sessions, run_id, RoundSnapshot
                ).items()
            }
            gains = sorted(
                self.checkpoints.saved_inputs(
                    self.store.sessions, run_id, InformationGainSummary
                ).values(),
                key=lambda g: g.round,
            )
            # Recover the small window between a committed verification and gain bookkeeping.
            if state.run.current_phase is not WorkflowPhase.VERIFY and any(
                step.logical_step_key == state.run.last_completed_step_key
                and step.step_type is StepType.VALIDATION
                for step in state.steps
            ):
                task = self._latest_completed_task(state)
                if (
                    task.round in before_round
                    and not any(g.round == task.round for g in gains)
                    and not any(
                        t.status is ResearchTaskStatus.PENDING and t.round == task.round
                        for t in state.tasks
                    )
                ):
                    gains.append(
                        self._pinned_input(
                            run_id,
                            f"round:gain:{task.round}",
                            self.gain.compare(
                                before_round[task.round],
                                self.gain.snapshot(self.store, state),
                                round_number=task.round,
                            ),
                        )
                    )
            for gain in gains:
                no_progress.observe(gain)
                before_round.pop(gain.round, None)
            if (
                state.run.current_phase is not WorkflowPhase.REPORT
                and no_progress.consecutive >= self.config.no_progress_rounds
            ):
                return await self._blocked(run_id, trace, gains, "NO_INFORMATION_GAIN")
        if state.run.current_phase is WorkflowPhase.CREATED:
            await self._bootstrap(state)
            trace.append("PLAN")
            state = self.store.state(run_id)
        if state.run.current_phase is WorkflowPhase.PLAN:
            if not self._can_dispatch_model(state):
                return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
            try:
                await self._plan(state)
            except RunBudgetExceededError as error:
                return await self._blocked(
                    run_id, trace, gains, "BUDGET_EXHAUSTED", rejection=error
                )
            state = self.store.state(run_id)

        while state.run.current_phase is not WorkflowPhase.REPORT:
            if state.run.current_phase is WorkflowPhase.COLLECT:
                if (
                    not self._collection_headroom(state)
                    and state.claims
                    and any(t.status is ResearchTaskStatus.COMPLETED for t in state.tasks)
                ):
                    await self._finish_existing(state, Route.ANALYZE)
                    state = self.store.state(run_id)
                    continue
                pending = tuple(
                    task for task in state.tasks if task.status is ResearchTaskStatus.PENDING
                )
                if not pending:
                    if not self.store.open_gaps(state):
                        return await self._blocked(
                            run_id, trace, gains, "NO_ACTIONABLE_RESEARCH_TASK"
                        )
                    if not self._can_dispatch_model(state):
                        return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                    try:
                        followup = await self._route_followup(state)
                        if followup.route is Route.BLOCKED:
                            proposal_stop_reason = followup.reason
                    except RunBudgetExceededError as error:
                        return await self._blocked(
                            run_id, trace, gains, "BUDGET_EXHAUSTED", rejection=error
                        )
                    state = self.store.state(run_id)
                    continue
                task = sorted(pending, key=lambda item: (-item.priority, item.task_id))[0]
                if not self._can_research(state, task):
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                before_round.setdefault(
                    task.round,
                    self._pinned_input(
                        run_id, f"round:before:{task.round}", self.gain.snapshot(self.store, state)
                    ),
                )
                try:
                    research_result = await self._research(state, task)
                    if (
                        research_result.researcher_errors
                        and self.store.state(run_id).run.status is RunStatus.BLOCKED
                    ):
                        proposal_stop_reason = research_result.researcher_errors[0]
                except RunBudgetExceededError as error:
                    if str(error).startswith("stage model reservation") and state.claims:
                        await self._finish_existing(self.store.state(run_id), Route.ANALYZE)
                        state = self.store.state(run_id)
                        continue
                    return await self._blocked(
                        run_id, trace, gains, "BUDGET_EXHAUSTED", rejection=error
                    )
                trace.append("COLLECT")
                state = self.store.state(run_id)
                continue

            if state.run.current_phase is WorkflowPhase.ANALYZE:
                if not self._collection_headroom(state) and state.claims:
                    await self._finish_existing(state, Route.VERIFY)
                    state = self.store.state(run_id)
                    continue
                if not self._can_dispatch_model(state):
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                task = self._latest_completed_task(state)
                research = self._latest_step_output(
                    state,
                    StepType.RESEARCH,
                    ResearchExecutionResult,
                    logical_step_key=f"research:{task.title}:round-{task.round}",
                )
                try:
                    analysis_result = await self._analyze(state, task, research)
                    if analysis_result.rejected_candidate_keys == ("INVALID_ANALYSIS_PROPOSAL",):
                        proposal_stop_reason = self._proposal_stop_detail("analysis")
                        proposal_stop_reason += (
                            " 校验项："
                            + analysis_result.grounding_diagnostics.get(
                                "proposal_error", "INVALID_RESPONSE"
                            )
                        )
                    elif analysis_result.rejected_candidate_keys == ("ANALYSIS_RETRY_LIMIT",):
                        proposal_stop_reason = self._analysis_retry_stop_detail()
                except RunBudgetExceededError as error:
                    if str(error).startswith("stage model reservation") and state.claims:
                        await self._finish_existing(self.store.state(run_id), Route.VERIFY)
                        state = self.store.state(run_id)
                        continue
                    return await self._blocked(
                        run_id, trace, gains, "BUDGET_EXHAUSTED", rejection=error
                    )
                trace.append("ANALYZE")
                state = self.store.state(run_id)
                continue

            if state.run.current_phase is WorkflowPhase.VERIFY:
                if self._verification_converged(state):
                    return await self._blocked(
                        run_id, trace, gains, "VERIFICATION_NO_INFORMATION_GAIN"
                    )
                batches = sum(
                    s.step_type is StepType.VALIDATION and s.status is ExecutionStepStatus.COMPLETED
                    for s in state.steps
                )
                if batches >= self.config.max_verification_batches:
                    return await self._blocked(run_id, trace, gains, "VERIFICATION_LIMIT_REACHED")
                if self.config.model_budget_reservations:
                    self.calls.verification_budget_policy = VerificationBudgetPolicy(
                        max_calls=self.config.max_verification_calls,
                        max_tokens=int(
                            state.budget.max_tokens * self.config.max_verification_token_fraction
                        ),
                    )
                if not self._can_dispatch_model(state):
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                task = self._latest_completed_task(state)
                try:
                    await self._verify(state, task)
                except RunBudgetExceededError as error:
                    return await self._blocked(
                        run_id,
                        trace,
                        gains,
                        "VERIFICATION_LIMIT_REACHED"
                        if str(error).startswith("VERIFICATION_LIMIT_REACHED")
                        else "BUDGET_EXHAUSTED",
                        rejection=error,
                    )
                trace.append("VERIFY")
                state = self.store.state(run_id)
                before = before_round.get(task.round)
                pending_in_round = any(
                    item.status is ResearchTaskStatus.PENDING and item.round == task.round
                    for item in state.tasks
                )
                if (
                    before is not None
                    and not pending_in_round
                    and state.run.current_phase is not WorkflowPhase.VERIFY
                ):
                    round_gain = self.gain.compare(
                        before,
                        self.gain.snapshot(self.store, state),
                        round_number=task.round,
                    )
                    round_gain = self._pinned_input(run_id, f"round:gain:{task.round}", round_gain)
                    gains.append(round_gain)
                    before_round.pop(task.round, None)
                    if state.run.current_phase is not WorkflowPhase.REPORT and no_progress.observe(
                        round_gain
                    ):
                        return await self._blocked(run_id, trace, gains, "NO_INFORMATION_GAIN")
                continue

            return await self._blocked(run_id, trace, gains, "ILLEGAL_RUNTIME_PHASE")

        final = self.store.state(run_id)
        termination: Literal["READY_FOR_REPORT", "BLOCKED", "FAILED"] = (
            "READY_FOR_REPORT" if final.run.status is RunStatus.READY_FOR_REPORT else "BLOCKED"
        )
        reason = (
            "POLICY_SUFFICIENT"
            if termination == "READY_FOR_REPORT"
            else proposal_stop_reason or final.run.interruption_reason or "BLOCKED"
        )
        return FeedbackLoopResult(
            run_id=run_id,
            termination=termination,
            reason=reason,
            rounds_completed=final.budget.research_rounds_used,
            phase_trace=tuple(trace),
            information_gain=tuple(gains),
            report_input=ReportInput(summary=self.context.summary(final, reason)),
        )

    async def _bootstrap(self, state: FeedbackState) -> None:
        transition = PhaseTransition(action="ENTER_PLAN", reason="start feedback loop")

        async def handler() -> StepOutcome:
            return StepOutcome(proposal=transition, route=Route.PLAN)

        await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key="workflow:enter-plan",
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.CREATED,
            step_type=StepType.OTHER,
            agent_role=AgentRole.HARNESS,
            owner_instance_id=self.owner,
            semantic_input=transition,
            output_model=PhaseTransition,
            handler=handler,
            timeout_seconds=self.config.step_timeout_seconds,
        )

    def _collection_headroom(self, state: FeedbackState) -> bool:
        if self.config.model_budget_reservations and any(
            step.logical_step_key
            and step.logical_step_key.startswith("budget:finish:")
            and step.status is ExecutionStepStatus.COMPLETED
            for step in state.steps
        ):
            return False
        return not self.config.model_budget_reservations or self.stage_budget.admits(
            state.budget, "researcher.research", 1
        )

    async def _finish_existing(self, state: FeedbackState, route: Route) -> None:
        transition = PhaseTransition(
            action="FINISH_EXISTING",
            reason="COLLECTION_RESERVE_REACHED: finish existing material without new collection",
        )

        async def handler() -> StepOutcome:
            return StepOutcome(proposal=transition, route=route)

        await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=f"budget:finish:{state.run.current_phase.value}:{state.run.checkpoint_version}",
            workflow_version=self.config.workflow_version,
            phase=state.run.current_phase,
            step_type=StepType.OTHER,
            agent_role=AgentRole.HARNESS,
            owner_instance_id=self.owner,
            semantic_input=transition,
            output_model=PhaseTransition,
            handler=handler,
            timeout_seconds=self.config.step_timeout_seconds,
        )

    async def _plan(self, state: FeedbackState) -> PlanProposal:
        request = self._pinned_input(
            state.run.run_id, "planning:initial", self.context.planner(state)
        )
        scope = StepPortScope(self.calls)

        async def handler() -> StepOutcome:
            proposal = await ModelPlannerAgent(scope.model("planner.plan")).plan(request)
            tasks = self._materialize_tasks(state, proposal.tasks, round_number=1)
            if not tasks:
                raise ProposalGuardError("planner produced no new ResearchTask")
            return StepOutcome(
                proposal=proposal,
                route=Route.COLLECT,
                business_outputs=tasks,
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key="planning:initial",
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.PLAN,
            step_type=StepType.PLANNING,
            agent_role=AgentRole.SUPERVISOR,
            owner_instance_id=self.owner,
            semantic_input=request,
            output_model=PlanProposal,
            handler=handler,
            on_step_started=scope.bind,
            timeout_seconds=self.config.step_timeout_seconds,
        )

    async def _route_followup(self, state: FeedbackState) -> RouteProposal:
        plan = self.context.planner(state)
        request = RouteInput(
            case_key=plan.case_key,
            gaps=plan.unresolved_gaps,
            questions=plan.questions,
            coverage=plan.coverage,
            prior_task_summaries=plan.prior_task_summaries,
            budget=plan.budget,
        )
        round_number = state.budget.research_rounds_used + 1
        if self.config.workflow_version == RESUMABLE_WORKFLOW_VERSION:
            interrupted = next(
                (
                    step
                    for step in reversed(state.steps)
                    if step.logical_step_key == state.run.current_step_key
                    and step.logical_step_key is not None
                    and step.logical_step_key.startswith("planning:feedback:round-")
                    and step.status is not ExecutionStepStatus.COMPLETED
                ),
                None,
            )
            if interrupted is not None:
                assert interrupted.logical_step_key is not None
                round_number = int(interrupted.logical_step_key.rsplit("-", 1)[1])
        logical_key = f"planning:feedback:round-{round_number}"
        request = self._pinned_input(state.run.run_id, logical_key, request)
        scope = StepPortScope(self.calls)

        async def handler() -> StepOutcome:
            try:
                proposal = await ModelPlannerAgent(scope.model("planner.route")).route(request)
                if proposal.route is not Route.COLLECT:
                    raise ProposalGuardError("Supervisor feedback route must request COLLECT")
                tasks = self._materialize_tasks(state, proposal.tasks, round_number=round_number)
                if not tasks:
                    raise ProposalGuardError("Supervisor produced no new follow-up ResearchTask")
            except (ProposalGuardError, InvalidProviderResponseError):
                reason = self._proposal_stop_detail("follow-up planning")
                return StepOutcome(
                    proposal=RouteProposal(route=Route.BLOCKED, reason=reason),
                    route=Route.BLOCKED,
                    business_outputs=self._termination_gap(state, reason),
                )
            return StepOutcome(
                proposal=proposal,
                route=Route.COLLECT,
                business_outputs=tasks,
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=logical_key,
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.COLLECT,
            step_type=StepType.PLANNING,
            agent_role=AgentRole.SUPERVISOR,
            owner_instance_id=self.owner,
            semantic_input=request,
            output_model=RouteProposal,
            handler=handler,
            on_step_started=scope.bind,
            research_round=round_number,
            timeout_seconds=self.config.step_timeout_seconds,
        )

    async def _research(
        self,
        state: FeedbackState,
        task: ResearchTask,
    ) -> ResearchExecutionResult:
        request = self.context.researcher(state, task)
        scope = StepPortScope(self.calls)
        logical_key = f"research:{task.title}:round-{task.round}"
        request = self._pinned_input(state.run.run_id, logical_key, request)

        async def handler() -> StepOutcome:
            researcher_errors: tuple[str, ...] = ()
            try:
                if self.config.research_workers > 1:
                    proposal, researcher_errors = await research_team(
                        request,
                        scope.model,
                        workers=self.config.research_workers,
                        max_queries=self.config.queries_per_researcher,
                        progress=self.progress,
                    )
                else:
                    proposal = await ModelResearcherAgent(
                        scope.model("researcher.propose")
                    ).research(request)
            except (ProposalGuardError, InvalidProviderResponseError):
                return self._blocked_research_outcome(state)
            guard = QueryGuard(max_length=self.config.max_query_length)
            executed = {
                normalize_query(query) for prior in state.tasks for query in prior.query_hints
            }
            task_queries = {normalize_query(query) for query in task.query_hints}
            remaining = request.remaining_search_calls
            rejected: list[str] = []
            accepted = []
            for intent in proposal.queries:
                try:
                    normalized = guard.validate(
                        intent,
                        task_key=task.title,
                        target_text=(
                            request.target_question.text
                            if request.target_question is not None
                            else task.objective
                        ),
                        purpose=intent.purpose,
                        executed_normalized=executed,
                        task_queries=task_queries,
                        remaining_budget=remaining,
                    )
                except ProposalGuardError:
                    rejected.append(intent.query_key)
                    continue
                accepted.append((intent, normalized))
                executed.add(normalized)
                task_queries.add(normalized)
                remaining -= 1
            if not accepted:
                return self._blocked_research_outcome(state)

            acquisition = SourceAcquisitionService(
                repository=self.repository,
                blobs=self.blobs,
                search=scope.search("research.search"),
                fetch=scope.fetch("research.fetch"),
                parsers=self.parsers,
                clock=self.clock,
                tolerate_fetch_errors=True,
                reuse_accepted_sources=self.config.deduplicate_material,
            )
            outputs: list[PersistedEntity] = []
            source_ids: list[str] = []
            artifact_ids: list[str] = []
            gap_ids: list[str] = []
            valid_count = 0
            seen_entity_ids: set[tuple[str, str]] = set()
            max_results = max(
                1,
                min(
                    request.budget.sources_remaining,
                    request.budget.fetch_calls_remaining,
                ),
            )
            prepared_queries: list[PreparedAcquisition] = []
            if self.config.search_concurrency > 1 or self.config.fetch_concurrency > 1:
                prepared_queries, acquisition_errors = await acquisition_batch(
                    [intent for intent, _ in accepted],
                    search=scope.search,
                    service=lambda key, semaphore: SourceAcquisitionService(
                        repository=self.repository,
                        blobs=self.blobs,
                        search=scope.search("research.unused"),
                        fetch=scope.fetch(key),
                        parsers=self.parsers,
                        clock=self.clock,
                        fetch_concurrency=self.config.fetch_concurrency,
                        tolerate_fetch_errors=True,
                        reuse_accepted_sources=self.config.deduplicate_material,
                        fetch_semaphore=semaphore,
                    ),
                    investigation_id=state.investigation.investigation_id,
                    run_id=state.run.run_id,
                    logical_key=logical_key,
                    search_limit=self.config.search_concurrency,
                    fetch_limit=self.config.fetch_concurrency,
                    page_budget=min(max_results, self.config.max_artifacts),
                )
                researcher_errors += acquisition_errors
            else:
                for intent, _normalized in accepted:
                    prepared_queries.append(
                        await acquisition.prepare(
                            AcquisitionRequest(
                                investigation_id=state.investigation.investigation_id,
                                run_id=state.run.run_id,
                                query=intent.query,
                                max_results=min(intent.max_results, max_results),
                            ),
                            logical_step_key=logical_key,
                        )
                    )
            for prepared in prepared_queries:
                valid_count += prepared.result.valid_source_count
                for item in prepared.result.sources:
                    source_ids.append(item.source_id)
                    artifact_ids.extend(item.artifact_ids)
                    gap_ids.extend(item.gap_ids)
                for entity in prepared.business_outputs:
                    identity = self._entity_identity(entity)
                    if identity in seen_entity_ids:
                        continue
                    seen_entity_ids.add(identity)
                    outputs.append(entity)
            if researcher_errors or not source_ids:
                gap = ResearchGap(
                    gap_id=stable_id("G", state.run.run_id, logical_key, "discovery-limitation"),
                    investigation_id=state.investigation.investigation_id,
                    run_id=state.run.run_id,
                    gap_type=ResearchGapType.UNREADABLE_SOURCE,
                    target_question_id=task.target_question_id,
                    reason="; ".join(researcher_errors) or "NO_NEW_ACCESSIBLE_SOURCE",
                    severity=GapSeverity.MEDIUM,
                    status=GapStatus.OPEN,
                    suggested_actions=("Search additional independent and accessible sources.",),
                    created_at=self.clock(),
                )
                outputs.append(gap)
                gap_ids.append(gap.gap_id)
            # Failed fetches have no snapshot but their persisted gap retains source_id.
            # Count once per run, including replay where the global Source already exists.
            prior_source_ids = {item.source_id for item in state.sources} | {
                gap.source_id for gap in state.gaps if gap.source_id
            }
            new_sources = len(set(source_ids) - prior_source_ids)
            result = ResearchExecutionResult(
                proposal=proposal,
                researcher_errors=researcher_errors,
                acquired_source_ids=tuple(dict.fromkeys(source_ids)),
                artifact_ids=tuple(dict.fromkeys(artifact_ids)),
                acquisition_gap_ids=tuple(dict.fromkeys(gap_ids)),
                valid_source_count=valid_count,
                rejected_queries=tuple(rejected),
            )
            return StepOutcome(
                proposal=result,
                route=Route.ANALYZE if artifact_ids else Route.COLLECT,
                business_outputs=tuple(outputs),
                transaction_operations=(
                    CompleteResearchTaskOperation(
                        task_id=task.task_id,
                        query_hints=tuple(item.query for item, _ in accepted),
                        completed_at=self.clock(),
                    ),
                    ReserveSourcesOperation(
                        run_id=state.run.run_id,
                        count=new_sources,
                        updated_at=self.clock(),
                    ),
                ),
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=logical_key,
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.COLLECT,
            step_type=StepType.RESEARCH,
            agent_role=AgentRole.RESEARCHER,
            owner_instance_id=self.owner,
            semantic_input=request,
            output_model=ResearchExecutionResult,
            handler=handler,
            on_step_started=scope.bind,
            research_round=task.round,
            timeout_seconds=self.config.step_timeout_seconds,
        )

    async def _analyze(
        self,
        state: FeedbackState,
        task: ResearchTask,
        research: ResearchExecutionResult,
    ) -> AnalysisExecutionResult:
        bundle = self.context.analyst(
            state,
            task,
            current_artifact_ids=frozenset(research.artifact_ids),
        )
        scope = StepPortScope(self.calls)
        base_logical_key = f"analyze:{task.title}:round-{task.round}"
        prior_attempts = sorted(
            (
                item
                for item in state.steps
                if item.step_type is StepType.ANALYSIS
                and item.status is ExecutionStepStatus.COMPLETED
                and item.logical_step_key is not None
                and (
                    item.logical_step_key == base_logical_key
                    or item.logical_step_key.startswith(f"{base_logical_key}:feedback-")
                )
            ),
            key=lambda item: (item.completed_at or item.started_at, item.step_id),
        )
        logical_key = (
            base_logical_key
            if not prior_attempts
            else f"{base_logical_key}:feedback-{len(prior_attempts)}"
        )
        dependency_key = (
            f"research:{task.title}:round-{task.round}"
            if not prior_attempts
            else prior_attempts[-1].logical_step_key
        )
        assert dependency_key is not None

        bundle = replace(
            bundle, request=self._pinned_input(state.run.run_id, logical_key, bundle.request)
        )

        async def handler() -> StepOutcome:
            analyst = ModelAnalystAgent(scope.model("analyst.extract"))
            if len(prior_attempts) >= self.config.max_analysis_attempts:
                from marketpulse.investigation.agents.contracts import AnalysisProposal

                reason = self._analysis_retry_stop_detail()
                return StepOutcome(
                    proposal=AnalysisExecutionResult(
                        proposal=AnalysisProposal(),
                        rejected_candidate_keys=("ANALYSIS_RETRY_LIMIT",),
                    ),
                    route=Route.BLOCKED,
                    business_outputs=self._termination_gap(state, reason),
                )
            try:
                proposal = await analyst.analyze(
                    bundle.request, ground_quotes=self.config.ground_model_quotes
                )
            except InvalidProviderResponseError as error:
                from marketpulse.investigation.agents.contracts import AnalysisProposal

                issues = "; ".join(error.validation_issues) or "INVALID_RESPONSE"
                reason = self._proposal_stop_detail("analysis") + " 校验项：" + issues
                return StepOutcome(
                    proposal=AnalysisExecutionResult(
                        proposal=AnalysisProposal(),
                        rejected_candidate_keys=("INVALID_ANALYSIS_PROPOSAL",),
                        grounding_diagnostics={"proposal_error": issues},
                    ),
                    route=Route.BLOCKED,
                    business_outputs=self._termination_gap(state, reason),
                )
            evidence_by_key: dict[str, Evidence] = {}
            evidence_outputs: list[Evidence] = []
            existing_evidence = {item.evidence_id: item for item in state.evidence}
            rejected: list[str] = []
            analysis_gaps: list[ResearchGap] = []
            artifacts = {item.artifact_id: item for item in state.artifacts}
            snapshots = {item.snapshot_id: item for item in state.snapshots}
            for evidence_candidate in proposal.evidence:
                artifact_id = bundle.artifact_ids[evidence_candidate.artifact_key]
                artifact = artifacts[artifact_id]
                snapshot = snapshots[artifact.snapshot_id]
                try:
                    materialized_evidence = EvidenceCreationGuard(self.integrity).create(
                        evidence_candidate,
                        run_id=state.run.run_id,
                        artifact=artifact,
                        snapshot=snapshot,
                        created_by_step_id=scope.step.step_id,
                        research_task_id=task.task_id,
                        extracted_at=self.clock(),
                    )
                except ProposalGuardError as error:
                    rejected.append(evidence_candidate.evidence_key)
                    analysis_gaps.append(
                        self._analysis_error_gap(
                            state,
                            task,
                            candidate_key=evidence_candidate.evidence_key,
                            stage="evidence extraction",
                            error=error,
                        )
                    )
                    continue
                persisted_evidence = existing_evidence.get(
                    materialized_evidence.evidence_id, materialized_evidence
                )
                evidence_by_key[evidence_candidate.evidence_key] = persisted_evidence
                if materialized_evidence.evidence_id not in existing_evidence:
                    evidence_outputs.append(materialized_evidence)
            candidates: list[ClaimCandidate] = []
            for claim_candidate in proposal.claims:
                if claim_candidate.atomicity.is_atomic:
                    candidates.append(claim_candidate)
                    continue
                try:
                    repaired = await analyst.decompose(
                        ClaimDecompositionInput(
                            composite_claim=claim_candidate,
                            target_question=bundle.request.target_question,
                        )
                    )
                except (InvalidProviderResponseError, ValueError) as error:
                    rejected.append(claim_candidate.claim_key)
                    analysis_gaps.append(
                        self._analysis_error_gap(
                            state,
                            task,
                            candidate_key=claim_candidate.claim_key,
                            stage="claim decomposition",
                            error=error,
                        )
                    )
                    continue
                candidates.extend(repaired.subclaims)

            existing = list(state.claims)
            claim_outputs: list[Claim] = []
            claim_by_key: dict[str, Claim] = {}
            reused: list[str] = []
            for atomic_candidate in candidates:
                try:
                    materialized = ClaimGuard().materialize(
                        atomic_candidate,
                        investigation_id=state.investigation.investigation_id,
                        run_id=state.run.run_id,
                        existing_claims=tuple(existing),
                        created_by_step_id=scope.step.step_id,
                        research_task_id=task.task_id,
                        now=self.clock(),
                    )
                except ProposalGuardError as error:
                    rejected.append(atomic_candidate.claim_key)
                    analysis_gaps.append(
                        self._analysis_error_gap(
                            state,
                            task,
                            candidate_key=atomic_candidate.claim_key,
                            stage="claim normalization",
                            error=error,
                        )
                    )
                    continue
                claim_by_key[atomic_candidate.claim_key] = materialized.claim
                if materialized.reused:
                    reused.append(materialized.claim.claim_id)
                else:
                    existing.append(materialized.claim)
                    claim_outputs.append(materialized.claim)

            if not claim_by_key and not state.claims:
                analysis_gaps.append(
                    self._analysis_error_gap(
                        state,
                        task,
                        candidate_key="NO_VALID_CLAIM",
                        stage="claim extraction",
                        error=ProposalGuardError(
                            "Analyst produced no valid Claim for the investigation"
                        ),
                    )
                )

            relation_outputs = []
            relation_pairs = {(item.claim_id, item.evidence_id) for item in state.relations}
            relation_specs = list(proposal.relations)
            for relation_candidate in candidates:
                relation_specs.extend(self._implicit_relations(relation_candidate))
            for spec in relation_specs:
                claim = claim_by_key.get(spec.claim_key)
                relation_evidence = evidence_by_key.get(spec.evidence_key)
                if claim is None or relation_evidence is None:
                    continue
                pair = (claim.claim_id, relation_evidence.evidence_id)
                if pair in relation_pairs:
                    continue
                relation_pairs.add(pair)
                relation_outputs.append(
                    ClaimEvidenceRelation(
                        relation_id=stable_id("REL", *pair),
                        claim_id=claim.claim_id,
                        evidence_id=relation_evidence.evidence_id,
                        stance=spec.stance,
                        entailment_status=EntailmentStatus.PENDING,
                        created_at=self.clock(),
                    )
                )

            timeline_outputs = []
            existing_timeline_ids = {item.timeline_event_id for item in state.timeline_events}
            for timeline_candidate in proposal.timeline_events:
                evidence_ids = tuple(
                    evidence_by_key[key].evidence_id
                    for key in timeline_candidate.evidence_keys
                    if key in evidence_by_key
                )
                try:
                    event_time = (
                        datetime.fromisoformat(timeline_candidate.event_time.replace("Z", "+00:00"))
                        if timeline_candidate.event_time is not None
                        else None
                    )
                except ValueError as error:
                    # A free-form model date (including a range) is not one timestamp.
                    # Keep the recorded proposal, reject only this candidate, and validate
                    # the remaining evidence instead of rolling back the entire analysis.
                    rejected.append(timeline_candidate.timeline_key)
                    analysis_gaps.append(
                        self._analysis_error_gap(
                            state,
                            task,
                            candidate_key=timeline_candidate.timeline_key,
                            stage="timeline event_time (expected a single ISO-8601 date/time)",
                            error=error,
                        )
                    )
                    continue
                timeline_event = TimelineEvent(
                    timeline_event_id=stable_id(
                        "TE", state.run.run_id, timeline_candidate.timeline_key
                    ),
                    investigation_id=state.investigation.investigation_id,
                    run_id=state.run.run_id,
                    event_time=event_time,
                    time_precision=(TimePrecision.EXACT if event_time else TimePrecision.UNKNOWN),
                    description=timeline_candidate.description,
                    supporting_evidence_ids=evidence_ids,
                    validation_status=ValidationStatus.PENDING,
                )
                if timeline_event.timeline_event_id not in existing_timeline_ids:
                    timeline_outputs.append(timeline_event)

            observations: list[ConflictObservation] = []
            for observation_candidate in proposal.conflict_observations:
                claim = claim_by_key.get(observation_candidate.claim_key)
                observation_evidence = evidence_by_key.get(observation_candidate.evidence_key)
                if claim is None or observation_evidence is None:
                    continue
                try:
                    report_time = (
                        datetime.fromisoformat(
                            observation_candidate.report_time.replace("Z", "+00:00")
                        )
                        if observation_candidate.report_time is not None
                        else None
                    )
                except ValueError as error:
                    candidate_key = (
                        f"{observation_candidate.claim_key}:{observation_candidate.evidence_key}"
                    )
                    rejected.append(candidate_key)
                    analysis_gaps.append(
                        self._analysis_error_gap(
                            state,
                            task,
                            candidate_key=candidate_key,
                            stage="conflict report_time (expected a single ISO-8601 date/time)",
                            error=error,
                        )
                    )
                    continue
                observations.append(
                    ConflictObservation(
                        claim_id=claim.claim_id,
                        evidence_id=observation_evidence.evidence_id,
                        statement=observation_candidate.statement,
                        conflict_type=observation_candidate.conflict_type,
                        numeric_value=observation_candidate.numeric_value,
                        unit=observation_candidate.unit,
                        report_time=report_time,
                        scope=observation_candidate.scope,
                        definition=observation_candidate.definition,
                        methodology=observation_candidate.methodology,
                        report_stage=observation_candidate.report_stage,
                        directness=observation_candidate.directness,
                        specificity=observation_candidate.specificity,
                    )
                )
            result = AnalysisExecutionResult(
                grounding_diagnostics=analyst.grounding_diagnostics,
                proposal=proposal,
                evidence_ids=tuple(item.evidence_id for item in evidence_outputs),
                claim_ids=tuple(item.claim_id for item in claim_outputs),
                reused_claim_ids=tuple(dict.fromkeys(reused)),
                relation_ids=tuple(item.relation_id for item in relation_outputs),
                timeline_event_ids=tuple(item.timeline_event_id for item in timeline_outputs),
                rejected_candidate_keys=tuple(rejected),
                conflict_observations=tuple(observations),
            )
            business: tuple[PersistedEntity, ...] = (
                *evidence_outputs,
                *claim_outputs,
                *relation_outputs,
                *timeline_outputs,
                *(
                    gap
                    for gap in analysis_gaps
                    if all(existing.gap_id != gap.gap_id for existing in state.gaps)
                ),
            )
            open_analysis_gap_ids = tuple(
                gap.gap_id
                for gap in self.store.open_gaps(state)
                if gap.gap_type is ResearchGapType.ANALYSIS_ERROR
                and gap.target_question_id == task.target_question_id
            )
            operations: tuple[TransactionOperation, ...] = ()
            if not analysis_gaps and open_analysis_gap_ids:
                operations = (
                    ResolveGapsOperation(open_analysis_gap_ids, resolved_at=self.clock()),
                )
            return StepOutcome(
                proposal=result,
                # Verify retained LIVE claims even if some quotes were rejected. The
                # gaps remain open and drive further collection after verification.
                route=(
                    Route.ANALYZE
                    if analysis_gaps and not (self.config.ground_model_quotes and claim_by_key)
                    else Route.VERIFY
                ),
                business_outputs=business,
                transaction_operations=operations,
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=logical_key,
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.ANALYZE,
            step_type=StepType.ANALYSIS,
            agent_role=AgentRole.ANALYST,
            owner_instance_id=self.owner,
            semantic_input=bundle.request,
            output_model=AnalysisExecutionResult,
            handler=handler,
            on_step_started=scope.bind,
            dependency_keys=(dependency_key,),
            timeout_seconds=self.config.step_timeout_seconds,
        )

    def _verification_converged(self, state: FeedbackState) -> bool:
        """Two identical complete policy inputs/results with unchanged evidence stop work.

        A new Claim, quote, source, relation or conflict must not be hidden by this
        check. Exact final-input fingerprints are more conservative than status alone.
        """
        if not state.claims:
            return False
        for claim in state.claims:
            results = sorted(
                (v for v in state.validations if v.claim_id == claim.claim_id),
                key=lambda v: (v.created_at, v.validation_id),
            )
            if len(results) < 2:
                return False
            last, previous = results[-1], results[-2]
            if (
                last.policy_version != self.validation_policy.VERSION
                or last.input_fingerprint != previous.input_fingerprint
                or last.status != previous.status
            ):
                return False
            ids = tuple(r.evidence_id for r in state.relations if r.claim_id == claim.claim_id)
            if last.evidence_set_hash != self.validation_policy._evidence_set_hash(
                state.evidence, ids
            ):
                return False
            if set(last.conflict_set_refs) != {
                c.conflict_id for c in state.conflicts if claim.claim_id in c.claim_ids
            }:
                return False
            if set(last.validation_basis_payload.get("unresolved_conflict_ids", [])) != {
                c.conflict_id
                for c in state.conflicts
                if claim.claim_id in c.claim_ids and str(c.resolution_status) == "UNRESOLVED"
            }:
                return False
        return True

    async def _verify(
        self,
        state: FeedbackState,
        task: ResearchTask,
    ) -> VerificationExecutionResult:
        state = publisher_state(state, self.blobs)
        base_logical_key = f"verify:{task.title}:round-{task.round}"
        prior_batches = sorted(
            (
                item
                for item in state.steps
                if item.step_type is StepType.VALIDATION
                and item.status is ExecutionStepStatus.COMPLETED
                and item.logical_step_key is not None
                and (
                    item.logical_step_key == base_logical_key
                    or item.logical_step_key.startswith(f"{base_logical_key}:batch-")
                )
            ),
            key=lambda item: (item.completed_at or item.started_at, item.step_id),
        )
        already_validated: set[str] = set()
        for batch in prior_batches:
            if not batch.output_refs:
                continue
            prior_result = VerificationExecutionResult.model_validate_json(
                self.blobs.get_bytes(BlobRef.from_uri(batch.output_refs[0]))
            )
            already_validated.update(item.claim_id for item in prior_result.validations)
        bundle = self.context.verifier(
            state,
            exclude_claim_ids=frozenset(already_validated),
        )
        if not bundle.request.claims:
            if not self._collection_headroom(state):
                await self._blocked(state.run.run_id, [], [], "COLLECTION_RESERVE_REACHED")
                return VerificationExecutionResult(
                    verifier_proposals=(),
                    validations=(),
                    route_reason="COLLECTION_RESERVE_REACHED",
                )
            raise RuntimeError("Verifier batch has no remaining Claim")
        scope = StepPortScope(self.calls)
        logical_key = (
            base_logical_key
            if not prior_batches
            else f"{base_logical_key}:batch-{len(prior_batches)}"
        )
        analysis_steps = sorted(
            (
                item
                for item in state.steps
                if item.step_type is StepType.ANALYSIS
                and item.status is ExecutionStepStatus.COMPLETED
                and item.logical_step_key is not None
                and (
                    item.logical_step_key == f"analyze:{task.title}:round-{task.round}"
                    or item.logical_step_key.startswith(
                        f"analyze:{task.title}:round-{task.round}:feedback-"
                    )
                )
            ),
            key=lambda item: (item.completed_at or item.started_at, item.step_id),
        )
        dependency_key = (
            prior_batches[-1].logical_step_key
            if prior_batches
            else analysis_steps[-1].logical_step_key
        )
        assert dependency_key is not None

        bundle = replace(
            bundle, request=self._pinned_input(state.run.run_id, logical_key, bundle.request)
        )
        workers = self._pinned_input(
            state.run.run_id,
            logical_key + ":workers",
            WorkerCheckpoint(
                workers=min(
                    self.config.research_workers,
                    max(1, state.budget.max_model_calls - state.budget.model_calls_used),
                )
            ),
        ).workers

        async def handler() -> StepOutcome:
            cached = ()
            if self.config.reuse_semantic_judgments:
                saved = self.checkpoints.saved_inputs(
                    self.store.sessions, state.run.run_id, VerificationInput
                )
                previous = []
                for step in state.steps:
                    if (
                        step.step_type is not StepType.VALIDATION
                        or step.status is not ExecutionStepStatus.COMPLETED
                    ):
                        continue
                    if step.logical_step_key not in saved or not step.output_refs:
                        continue
                    output = VerificationExecutionResult.model_validate_json(
                        self.blobs.get_bytes(BlobRef.from_uri(step.output_refs[0]))
                    )
                    previous.extend(
                        (saved[step.logical_step_key], p) for p in output.verifier_proposals
                    )
                cached = reusable_judgments(bundle.request, tuple(previous))
            cached_claims = {j.claim_key for j in cached}
            fresh = bundle.request.model_copy(
                update={
                    "claims": tuple(
                        c
                        for c in bundle.request.claims
                        if c.claim_key not in cached_claims
                        and (c.supporting_evidence_keys or c.contradicting_evidence_keys)
                    ),
                }
            )
            if not fresh.claims:
                proposal = VerificationProposal()
            elif self.config.research_workers > 1:
                snapshots = {s.snapshot_id: s.source_id for s in state.snapshots}
                evidence_sources = {
                    key: snapshots[e.snapshot_id]
                    for key, evidence_id in bundle.evidence_ids.items()
                    for e in state.evidence
                    if e.evidence_id == evidence_id
                }
                proposal = await verification_team(
                    fresh,
                    scope.model,
                    workers=workers,
                    evidence_sources=evidence_sources if self.config.metadata_chars else None,
                )
            else:
                proposal = await ModelVerifierAgent(scope.model("verifier.entailment")).verify(
                    fresh
                )
            proposal = proposal.model_copy(update={"judgments": (*cached, *proposal.judgments)})
            validate_agent_proposal(bundle.request, proposal)
            observations = self._all_observations(state)
            summaries = []
            operations: list[TransactionOperation] = []
            policy_gaps: list[ResearchGap] = []
            for candidate in bundle.request.claims:
                claim_id = bundle.claim_ids[candidate.claim_key]
                claim = next(item for item in state.claims if item.claim_id == claim_id)
                supplements = tuple(
                    s for s in proposal.qualifier_supplements if s.claim_key == candidate.claim_key
                )
                if supplements:
                    for supplement in supplements:
                        proof = next(
                            e
                            for e in state.evidence
                            if e.evidence_id == bundle.evidence_ids[supplement.evidence_key]
                        )
                        integrity = self.integrity.validate_reference(
                            evidence_id=proof.evidence_id,
                            evidence_by_id={e.evidence_id: e for e in state.evidence},
                            snapshot_by_id={s.snapshot_id: s for s in state.snapshots},
                            artifact_by_id={a.artifact_id: a for a in state.artifacts},
                        )
                        if not integrity.valid:
                            raise ProposalGuardError(
                                "qualifier supplement evidence failed integrity"
                            )
                    operations.append(
                        PersistQualifierSupplementsOperation(
                            claim=claim,
                            supplements=supplements,
                            evidence_ids=bundle.evidence_ids,
                            created_at=self.clock(),
                        )
                    )
                    claim = claim.model_copy(
                        update={
                            "qualifiers": supplemented_qualifiers(claim.qualifiers, supplements)
                        }
                    )
                relations = tuple(item for item in state.relations if item.claim_id == claim_id)
                evidence_ids = {item.evidence_id for item in relations}
                evidence = tuple(
                    item for item in state.evidence if item.evidence_id in evidence_ids
                )
                snapshot_ids = {item.snapshot_id for item in evidence}
                snapshots = tuple(
                    item for item in state.snapshots if item.snapshot_id in snapshot_ids
                )
                artifact_ids = {
                    item.artifact_id for item in evidence if item.artifact_id is not None
                }
                artifacts = tuple(
                    item for item in state.artifacts if item.artifact_id in artifact_ids
                )
                source_ids = {item.source_id for item in snapshots}
                sources = tuple(item for item in state.sources if item.source_id in source_ids)
                judgments = tuple(
                    self._semantic_judgment(
                        state.run.run_id,
                        claim_id,
                        bundle.evidence_ids[item.evidence_key],
                        item,
                        task.task_id,
                    )
                    for item in proposal.judgments
                    if item.claim_key == candidate.claim_key
                )
                validation_sequence = 1 + sum(
                    item.claim_id == claim_id for item in state.validations
                )
                validation_hash = stable_id(
                    "VAL",
                    state.run.run_id,
                    claim_id,
                    task.task_id,
                    str(task.round),
                )
                validation_id = (
                    f"VAL-{validation_sequence:04d}-{validation_hash.removeprefix('VAL-')}"
                )
                request = ValidationRequest(
                    validation_id=validation_id,
                    created_at=self.clock(),
                    claim=claim,
                    target_question_id=task.target_question_id,
                    relations=relations,
                    evidence=evidence,
                    snapshots=snapshots,
                    artifacts=artifacts,
                    sources=sources,
                    semantic_judgments=judgments,
                    conflict_observations=tuple(
                        item for item in observations if item.claim_id == claim_id
                    ),
                    existing_conflicts=tuple(
                        item for item in state.conflicts if claim_id in item.claim_ids
                    ),
                )
                outcome = self.validation_policy.validate(request)
                policy_gaps.extend(outcome.research_gaps)
                operations.append(PersistValidationOperation(request=request, outcome=outcome))
                summaries.append(
                    ClaimValidationSummary(
                        claim_id=claim_id,
                        validation_id=validation_id,
                        status=outcome.result.status,
                        confidence=outcome.result.confidence,
                        gap_ids=tuple(item.gap_id for item in outcome.research_gaps),
                        conflict_ids=outcome.result.conflict_set_refs,
                        semantic_content_hash=outcome.semantic_content_hash,
                    )
                )
            old_gaps = tuple(
                item.gap_id
                for item in self.store.open_gaps(state)
                if item.target_claim_id in bundle.claim_ids.values()
            )
            if old_gaps:
                operations.insert(0, ResolveGapsOperation(old_gaps, resolved_at=self.clock()))
            pending = any(item.status is ResearchTaskStatus.PENDING for item in state.tasks)
            selected_claim_ids = set(bundle.claim_ids.values())
            remaining_claim_ids = (
                {item.claim_id for item in state.claims} - already_validated - selected_claim_ids
            )
            open_gap_elsewhere = any(
                item.gap_id not in set(old_gaps) for item in self.store.open_gaps(state)
            )
            if remaining_claim_ids:
                route = Route.VERIFY
            elif not self._collection_headroom(self.store.state(state.run.run_id)):
                route = (
                    Route.BLOCKED if policy_gaps or open_gap_elsewhere else Route.READY_FOR_REPORT
                )
            elif policy_gaps or pending or open_gap_elsewhere:
                route = Route.COLLECT
            else:
                route = Route.READY_FOR_REPORT
            result = VerificationExecutionResult(
                reused_semantic_pairs=len(cached),
                verifier_proposals=(proposal,),
                validations=tuple(summaries),
                route_reason=(
                    "ValidationPolicy produced ResearchGap"
                    if policy_gaps
                    else "additional bounded Verifier batch required"
                    if remaining_claim_ids
                    else "all current Claim profiles are sufficient"
                ),
            )
            return StepOutcome(
                proposal=result,
                route=route,
                transaction_operations=tuple(operations),
                business_outputs=self._termination_gap(state, "COLLECTION_RESERVE_REACHED")
                if route is Route.BLOCKED
                else (),
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=logical_key,
            workflow_version=self.config.workflow_version,
            phase=WorkflowPhase.VERIFY,
            step_type=StepType.VALIDATION,
            agent_role=AgentRole.VERIFIER,
            owner_instance_id=self.owner,
            semantic_input=bundle.request,
            output_model=VerificationExecutionResult,
            handler=handler,
            on_step_started=scope.bind,
            dependency_keys=(dependency_key,),
            timeout_seconds=self.config.step_timeout_seconds,
        )

    async def _blocked(
        self,
        run_id: str,
        trace: list[str],
        gains: list[InformationGainSummary],
        reason: str,
        *,
        rejection: str | RunBudgetExceededError | None = None,
    ) -> FeedbackLoopResult:
        state = self.store.state(run_id)
        detail = reason
        if reason in {"VERIFICATION_LIMIT_REACHED", "VERIFICATION_NO_INFORMATION_GAIN"}:
            cause = (
                "验证已达批次/调用/token 上限"
                if reason == "VERIFICATION_LIMIT_REACHED"
                else "完整验证输入与结果连续两次未变化"
            )
            detail += (
                f"；{cause}，停止重复验证并基于已有结果生成报告。"
                "未完成的声明仍保持原验证状态及缺口；补充直接证据后可发起新的调查。"
            )
        if reason == "BUDGET_EXHAUSTED" and self.config.retrieval_strategy == "bm25-passages-v1":
            from marketpulse.investigation.feedback.budget_diagnostics import (
                describe_budget_exhaustion,
            )

            detail = describe_budget_exhaustion(
                state.budget,
                rejected_dimension=str(rejection) if rejection is not None else None,
                requested_round=max(
                    (
                        task.round
                        for task in state.tasks
                        if task.status is ResearchTaskStatus.PENDING
                    ),
                    default=None,
                ),
            )
        snapshot_sources = {snapshot.source_id for snapshot in state.snapshots}
        if not any(snapshot.evidence_eligible for snapshot in state.snapshots) and any(
            gap.source_id
            and gap.source_id not in snapshot_sources
            and gap.gap_type is ResearchGapType.UNREADABLE_SOURCE
            for gap in state.gaps
        ):
            detail += (
                "；未获得可读取的合格来源；部分来源不可访问或被限流。"
                "请检查网络、稍后重试或提供可访问的原始材料。"
            )
        if state.run.current_phase is not WorkflowPhase.REPORT:
            transition = PhaseTransition(action="BLOCK", reason=reason)
            logical_key = f"workflow:block:{reason.casefold()}"
            pause_events: tuple[PersistedEntity, ...] = ()
            if (
                reason == "BUDGET_EXHAUSTED"
                and self.config.workflow_version == RESUMABLE_WORKFLOW_VERSION
            ):
                logical_key += f":{state.run.checkpoint_version}"
                pause_events = (
                    AuditEvent(
                        audit_event_id=stable_id("BUDGET-PAUSE", run_id, logical_key),
                        investigation_id=state.investigation.investigation_id,
                        run_id=run_id,
                        actor_type=AuditActorType.SYSTEM,
                        event_type="RUN_BUDGET_BLOCKED",
                        target_type="InvestigationRun",
                        target_id=run_id,
                        metadata={
                            "resume_phase": state.run.current_phase.value,
                            "resume_step_key": state.run.current_step_key,
                            "blocking_step_key": logical_key,
                            "gap_ids": [self._termination_gap_id(state, detail)],
                            "stage_required_tokens": (
                                rejection.required_tokens
                                if isinstance(rejection, RunBudgetExceededError)
                                else None
                            ),
                            "stage_role": (
                                rejection.role
                                if isinstance(rejection, RunBudgetExceededError)
                                else None
                            ),
                        },
                        created_at=self.clock(),
                    ),
                )

            async def handler() -> StepOutcome:
                return StepOutcome(
                    proposal=transition,
                    route=Route.BLOCKED,
                    business_outputs=(*self._termination_gap(state, detail), *pause_events),
                )

            await self.harness.run_step(
                run_id=run_id,
                logical_step_key=logical_key,
                terminal_transition=True,
                workflow_version=self.config.workflow_version,
                phase=state.run.current_phase,
                step_type=StepType.OTHER,
                agent_role=AgentRole.HARNESS,
                owner_instance_id=self.owner,
                semantic_input=transition,
                output_model=PhaseTransition,
                handler=handler,
                timeout_seconds=self.config.step_timeout_seconds,
            )
        final = self.store.state(run_id)
        return FeedbackLoopResult(
            run_id=run_id,
            termination="BLOCKED",
            reason=reason,
            rounds_completed=final.budget.research_rounds_used,
            phase_trace=tuple(trace),
            information_gain=tuple(gains),
            report_input=ReportInput(summary=self.context.summary(final, detail)),
        )

    def _materialize_tasks(
        self,
        state: FeedbackState,
        proposals: tuple[TaskProposal, ...],
        *,
        round_number: int,
    ) -> tuple[ResearchTask, ...]:
        known = {(item.title, item.target_question_id) for item in state.tasks}
        questions = {item.question_id for item in state.investigation.questions}
        gaps = {item.gap_key: item for item in self.context.gaps(state)}
        actual_gaps = {self.context._gap_view(state, item).gap_key: item for item in state.gaps}
        claim_ids = {claim_key(item): item.claim_id for item in state.claims}
        output = []
        for proposal in proposals:
            if proposal.target_question_key not in questions:
                raise ProposalGuardError("ResearchTask targets an unknown question")
            key = (proposal.task_key, proposal.target_question_key)
            if key in known:
                raise ProposalGuardError("ResearchTask duplicates prior workflow work")
            if proposal.origin_gap_key is not None and proposal.origin_gap_key not in gaps:
                raise ProposalGuardError("ResearchTask references an unknown open gap")
            known.add(key)
            now = self.clock()
            output.append(
                ResearchTask(
                    task_id=stable_id("T", state.run.run_id, proposal.task_key, str(round_number)),
                    investigation_id=state.investigation.investigation_id,
                    run_id=state.run.run_id,
                    target_question_id=proposal.target_question_key,
                    target_claim_id=(
                        claim_ids.get(proposal.target_claim_key)
                        if proposal.target_claim_key is not None
                        else None
                    ),
                    origin_gap_id=(
                        actual_gaps[proposal.origin_gap_key].gap_id
                        if proposal.origin_gap_key is not None
                        else None
                    ),
                    parent_task_id=(
                        self._latest_completed_task(state).task_id
                        if state.tasks and round_number > 1
                        else None
                    ),
                    title=proposal.task_key,
                    objective=proposal.objective,
                    purpose=proposal.purpose or proposal.objective,
                    status=ResearchTaskStatus.PENDING,
                    priority=proposal.priority,
                    preferred_source_types=proposal.preferred_source_types,
                    suggested_queries=proposal.suggested_queries,
                    round=round_number,
                    created_at=now,
                    updated_at=now,
                )
            )
        return tuple(output)

    def _all_observations(self, state: FeedbackState) -> tuple[ConflictObservation, ...]:
        observations: list[ConflictObservation] = []
        for step in state.steps:
            if (
                step.step_type is StepType.ANALYSIS
                and step.status is ExecutionStepStatus.COMPLETED
                and step.output_refs
                and step.output_schema_version == AnalysisExecutionResult.__name__
            ):
                result = AnalysisExecutionResult.model_validate_json(
                    self.blobs.get_bytes(BlobRef.from_uri(step.output_refs[0]))
                )
                observations.extend(result.conflict_observations)
        return tuple(observations)

    def _latest_step_output(
        self,
        state: FeedbackState,
        step_type: StepType,
        model: type[OutputT],
        *,
        logical_step_key: str | None = None,
    ) -> OutputT:
        steps = [
            item
            for item in state.steps
            if item.step_type is step_type
            and item.status is ExecutionStepStatus.COMPLETED
            and item.output_refs
            and (logical_step_key is None or item.logical_step_key == logical_step_key)
        ]
        if not steps:
            raise RuntimeError(f"missing completed {step_type.value} Step")
        step = max(steps, key=lambda item: (item.completed_at or item.started_at, item.step_id))
        return model.model_validate_json(
            self.blobs.get_bytes(BlobRef.from_uri(step.output_refs[0]))
        )

    @staticmethod
    def _latest_completed_task(state: FeedbackState) -> ResearchTask:
        completed = [item for item in state.tasks if item.status is ResearchTaskStatus.COMPLETED]
        if not completed:
            raise RuntimeError("no completed ResearchTask")
        return max(completed, key=lambda item: (item.round, item.completed_at, item.task_id))

    @staticmethod
    def _implicit_relations(candidate: ClaimCandidate) -> list[CandidateRelation]:
        return [
            *(
                CandidateRelation(
                    claim_key=candidate.claim_key,
                    evidence_key=key,
                    stance=RelationStance.SUPPORTS,
                )
                for key in candidate.supporting_evidence_keys
            ),
            *(
                CandidateRelation(
                    claim_key=candidate.claim_key,
                    evidence_key=key,
                    stance=RelationStance.CONTRADICTS,
                )
                for key in candidate.contradicting_evidence_keys
            ),
        ]

    def _semantic_judgment(
        self,
        run_id: str,
        claim_id: str,
        evidence_id: str,
        item: AgentSemanticJudgment,
        verification_key: str,
    ) -> SemanticJudgment:
        return SemanticJudgment(
            judgment_id=stable_id("J", run_id, claim_id, evidence_id, verification_key),
            run_id=run_id,
            claim_id=claim_id,
            evidence_id=evidence_id,
            judgment=item.entailment,
            reason=item.rationale,
            semantic_confidence=item.semantic_confidence,
            schema_version="SemanticJudgment-v2",
            created_at=self.clock(),
        )

    def _can_dispatch_model(self, state: FeedbackState) -> bool:
        budget = self.context.budget(state)
        return (
            budget.model_calls_remaining > 0
            and budget.tokens_remaining > 0
            and budget.active_time_ms_remaining > 0
        )

    def _can_research(self, state: FeedbackState, task: ResearchTask) -> bool:
        budget = self.context.budget(state)
        return (
            self._can_dispatch_model(state)
            and task.round <= state.budget.max_research_rounds
            and budget.search_calls_remaining > 0
            and budget.fetch_calls_remaining > 0
            and budget.sources_remaining > 0
        )

    def _termination_gap_id(self, state: FeedbackState, reason: str) -> str:
        if self.config.workflow_version == RESUMABLE_WORKFLOW_VERSION:
            return stable_id("GAP", state.run.run_id, reason, str(state.run.checkpoint_version))
        return stable_id("GAP", state.run.run_id, reason)

    @staticmethod
    def _analysis_retry_stop_detail() -> str:
        return (
            "ANALYSIS_RETRY_LIMIT：同一任务已达到分析重试上限；"
            "已保留材料和可用提案。请检查提案引用错误或补充新的相关原始材料，"
            "不要重复提交相同来源或仅增加预算。"
        )

    @staticmethod
    def _proposal_stop_detail(stage: str) -> str:
        return (
            f"INVALID_AGENT_PROPOSAL ({stage})：未形成可确认结论。"
            "模型未能提供通过结构、引用或去重校验的可执行提案；已保留采集来源和执行记录。"
            "请补充可访问的原始材料或更换模型后重新调查，不应通过增加重复查询绕过质量门。"
        )

    def _blocked_research_outcome(self, state: FeedbackState) -> StepOutcome:
        from marketpulse.investigation.agents.contracts import ResearchProposal

        reason = self._proposal_stop_detail("research queries")
        return StepOutcome(
            proposal=ResearchExecutionResult(
                proposal=ResearchProposal(queries=()),
                researcher_errors=(reason,),
            ),
            route=Route.BLOCKED,
            business_outputs=self._termination_gap(state, reason),
        )

    def _termination_gap(self, state: FeedbackState, reason: str) -> tuple[PersistedEntity, ...]:
        if any(item.reason == reason for item in self.store.open_gaps(state)):
            return ()
        now = self.clock()
        action = (
            "补充可访问的原始材料，检查或更换模型后重新调查；保留证据完整性校验"
            if reason.startswith("INVALID_AGENT_PROPOSAL")
            else "resume with a larger budget or new evidence source"
        )
        return (
            ResearchGap(
                gap_id=self._termination_gap_id(state, reason),
                investigation_id=state.investigation.investigation_id,
                run_id=state.run.run_id,
                gap_type=ResearchGapType.OTHER,
                reason=reason,
                missing_requirement="additional executable investigation capacity",
                suggested_action=action,
                severity=GapSeverity.BLOCKING,
                status=GapStatus.OPEN,
                suggested_actions=(action,),
                created_at=now,
            ),
        )

    def _analysis_error_gap(
        self,
        state: FeedbackState,
        task: ResearchTask,
        *,
        candidate_key: str,
        stage: str,
        error: Exception,
    ) -> ResearchGap:
        reason = f"{stage} failed for {candidate_key}: {type(error).__name__}"
        action = f"retry bounded {stage} with corrected structured evidence"
        return ResearchGap(
            gap_id=stable_id(
                "GAP",
                state.run.run_id,
                task.task_id,
                stage,
                candidate_key,
            ),
            investigation_id=state.investigation.investigation_id,
            run_id=state.run.run_id,
            gap_type=ResearchGapType.ANALYSIS_ERROR,
            target_question_id=task.target_question_id,
            target_claim_id=task.target_claim_id,
            reason=reason,
            missing_requirement=f"valid {stage} output",
            suggested_action=action,
            severity=GapSeverity.BLOCKING,
            status=GapStatus.OPEN,
            suggested_actions=(action,),
            created_at=self.clock(),
        )

    @staticmethod
    def _entity_identity(entity: PersistedEntity) -> tuple[str, str]:
        # Foreign keys are not entity identity: all pages share snapshot_id, and
        # multiple gaps can share source_id. Deduplicate only the actual primary key.
        primary_key = {
            Source: "source_id",
            SourceSnapshot: "snapshot_id",
            DocumentArtifact: "artifact_id",
            ResearchGap: "gap_id",
            Evidence: "evidence_id",
            Claim: "claim_id",
            ClaimEvidenceRelation: "relation_id",
            TimelineEvent: "timeline_event_id",
        }.get(type(entity))
        if primary_key is None:
            raise TypeError(f"unsupported feedback entity: {type(entity).__name__}")
        return type(entity).__name__, str(getattr(entity, primary_key))
