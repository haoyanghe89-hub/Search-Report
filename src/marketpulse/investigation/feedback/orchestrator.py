from __future__ import annotations

from collections.abc import Callable
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
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ResearchGap,
    TimelineEvent,
)
from marketpulse.investigation.domain.enums import (
    AgentRole,
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
from marketpulse.investigation.domain.runtime import ResearchTask
from marketpulse.investigation.domain.sources import Evidence
from marketpulse.investigation.feedback.context import AgentContextBuilder, claim_key
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
from marketpulse.investigation.feedback.store import (
    CompleteResearchTaskOperation,
    FeedbackState,
    FeedbackStore,
    ReserveSourcesOperation,
    ResolveGapsOperation,
)
from marketpulse.investigation.harness.calls import BoundExternalCalls
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.harness.runtime import InvestigationHarness, StepOutcome
from marketpulse.investigation.harness.scoped_ports import StepPortScope
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

    async def run(self, run_id: str) -> FeedbackLoopResult:
        trace: list[str] = []
        gains: list[InformationGainSummary] = []
        no_progress = NoProgressDetector(self.config.no_progress_rounds)
        before_round: dict[int, RoundSnapshot] = {}

        state = self.store.state(run_id)
        if state.run.current_phase is WorkflowPhase.CREATED:
            await self._bootstrap(state)
            trace.append("PLAN")
            state = self.store.state(run_id)
        if state.run.current_phase is WorkflowPhase.PLAN:
            if not self._can_dispatch_model(state):
                return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
            try:
                await self._plan(state)
            except RunBudgetExceededError:
                return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
            state = self.store.state(run_id)

        while state.run.current_phase is not WorkflowPhase.REPORT:
            if state.run.current_phase is WorkflowPhase.COLLECT:
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
                        await self._route_followup(state)
                    except RunBudgetExceededError:
                        return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                    state = self.store.state(run_id)
                    continue
                task = sorted(pending, key=lambda item: (-item.priority, item.task_id))[0]
                if not self._can_research(state, task):
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                before_round.setdefault(task.round, self.gain.snapshot(self.store, state))
                try:
                    await self._research(state, task)
                except RunBudgetExceededError:
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                trace.append("COLLECT")
                state = self.store.state(run_id)
                continue

            if state.run.current_phase is WorkflowPhase.ANALYZE:
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
                    await self._analyze(state, task, research)
                except RunBudgetExceededError:
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                trace.append("ANALYZE")
                state = self.store.state(run_id)
                continue

            if state.run.current_phase is WorkflowPhase.VERIFY:
                if not self._can_dispatch_model(state):
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
                task = self._latest_completed_task(state)
                try:
                    await self._verify(state, task)
                except RunBudgetExceededError:
                    return await self._blocked(run_id, trace, gains, "BUDGET_EXHAUSTED")
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
            else final.run.interruption_reason or "BLOCKED"
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

    async def _plan(self, state: FeedbackState) -> PlanProposal:
        request = self.context.planner(state)
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
        scope = StepPortScope(self.calls)

        async def handler() -> StepOutcome:
            proposal = await ModelPlannerAgent(scope.model("planner.route")).route(request)
            if proposal.route is not Route.COLLECT:
                raise ProposalGuardError("Supervisor feedback route must request COLLECT")
            tasks = self._materialize_tasks(
                state,
                proposal.tasks,
                round_number=round_number,
            )
            if not tasks:
                raise ProposalGuardError("Supervisor produced no new follow-up ResearchTask")
            return StepOutcome(
                proposal=proposal,
                route=Route.COLLECT,
                business_outputs=tasks,
            )

        return await self.harness.run_step(
            run_id=state.run.run_id,
            logical_step_key=f"planning:feedback:round-{round_number}",
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

        async def handler() -> StepOutcome:
            proposal = await ModelResearcherAgent(scope.model("researcher.propose")).research(
                request
            )
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
                raise ProposalGuardError("Researcher produced no executable query")

            acquisition = SourceAcquisitionService(
                repository=self.repository,
                blobs=self.blobs,
                search=scope.search("research.search"),
                fetch=scope.fetch("research.fetch"),
                parsers=self.parsers,
                clock=self.clock,
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
            for intent, _normalized in accepted:
                prepared = await acquisition.prepare(
                    AcquisitionRequest(
                        investigation_id=state.investigation.investigation_id,
                        run_id=state.run.run_id,
                        query=intent.query,
                        max_results=min(intent.max_results, max_results),
                    ),
                    logical_step_key=logical_key,
                )
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
            prior_source_ids = {item.source_id for item in state.sources}
            new_sources = len(set(source_ids) - prior_source_ids)
            result = ResearchExecutionResult(
                proposal=proposal,
                acquired_source_ids=tuple(dict.fromkeys(source_ids)),
                artifact_ids=tuple(dict.fromkeys(artifact_ids)),
                acquisition_gap_ids=tuple(dict.fromkeys(gap_ids)),
                valid_source_count=valid_count,
                rejected_queries=tuple(rejected),
            )
            return StepOutcome(
                proposal=result,
                route=Route.ANALYZE,
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

        async def handler() -> StepOutcome:
            analyst = ModelAnalystAgent(scope.model("analyst.extract"))
            proposal = await analyst.analyze(bundle.request)
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
                event_time = (
                    datetime.fromisoformat(timeline_candidate.event_time.replace("Z", "+00:00"))
                    if timeline_candidate.event_time is not None
                    else None
                )
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
                observations.append(
                    ConflictObservation(
                        claim_id=claim.claim_id,
                        evidence_id=observation_evidence.evidence_id,
                        statement=observation_candidate.statement,
                        conflict_type=observation_candidate.conflict_type,
                        numeric_value=observation_candidate.numeric_value,
                        unit=observation_candidate.unit,
                        report_time=(
                            datetime.fromisoformat(
                                observation_candidate.report_time.replace("Z", "+00:00")
                            )
                            if observation_candidate.report_time is not None
                            else None
                        ),
                        scope=observation_candidate.scope,
                        definition=observation_candidate.definition,
                        methodology=observation_candidate.methodology,
                        report_stage=observation_candidate.report_stage,
                        directness=observation_candidate.directness,
                        specificity=observation_candidate.specificity,
                    )
                )
            result = AnalysisExecutionResult(
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
                route=Route.ANALYZE if analysis_gaps else Route.VERIFY,
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

    async def _verify(
        self,
        state: FeedbackState,
        task: ResearchTask,
    ) -> VerificationExecutionResult:
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

        async def handler() -> StepOutcome:
            proposal = await ModelVerifierAgent(scope.model("verifier.entailment")).verify(
                bundle.request
            )
            observations = self._all_observations(state)
            summaries = []
            operations: list[TransactionOperation] = []
            policy_gaps: list[ResearchGap] = []
            for candidate in bundle.request.claims:
                claim_id = bundle.claim_ids[candidate.claim_key]
                claim = next(item for item in state.claims if item.claim_id == claim_id)
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
            elif policy_gaps or pending or open_gap_elsewhere:
                route = Route.COLLECT
            else:
                route = Route.READY_FOR_REPORT
            result = VerificationExecutionResult(
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
    ) -> FeedbackLoopResult:
        state = self.store.state(run_id)
        if state.run.current_phase is not WorkflowPhase.REPORT:
            transition = PhaseTransition(action="BLOCK", reason=reason)

            async def handler() -> StepOutcome:
                return StepOutcome(
                    proposal=transition,
                    route=Route.BLOCKED,
                    business_outputs=self._termination_gap(state, reason),
                )

            await self.harness.run_step(
                run_id=run_id,
                logical_step_key=f"workflow:block:{reason.casefold()}",
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
            report_input=ReportInput(summary=self.context.summary(final, reason)),
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
        return budget.model_calls_remaining > 0 and budget.active_time_ms_remaining > 0

    def _can_research(self, state: FeedbackState, task: ResearchTask) -> bool:
        budget = self.context.budget(state)
        return (
            self._can_dispatch_model(state)
            and task.round <= state.budget.max_research_rounds
            and budget.search_calls_remaining > 0
            and budget.fetch_calls_remaining > 0
            and budget.sources_remaining > 0
        )

    def _termination_gap(self, state: FeedbackState, reason: str) -> tuple[PersistedEntity, ...]:
        if any(item.reason == reason for item in self.store.open_gaps(state)):
            return ()
        now = self.clock()
        return (
            ResearchGap(
                gap_id=stable_id("GAP", state.run.run_id, reason),
                investigation_id=state.investigation.investigation_id,
                run_id=state.run.run_id,
                gap_type=ResearchGapType.OTHER,
                reason=reason,
                missing_requirement="additional executable investigation capacity",
                suggested_action="resume with a larger budget or new evidence source",
                severity=GapSeverity.BLOCKING,
                status=GapStatus.OPEN,
                suggested_actions=("resume with a larger budget or new evidence source",),
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
        for field in (
            "source_id",
            "snapshot_id",
            "artifact_id",
            "gap_id",
            "evidence_id",
            "claim_id",
            "relation_id",
            "timeline_event_id",
        ):
            value = getattr(entity, field, None)
            if value is not None:
                return type(entity).__name__, str(value)
        raise TypeError(f"unsupported feedback entity: {type(entity).__name__}")
