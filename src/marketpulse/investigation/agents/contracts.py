from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictType,
    RelationStance,
    ResearchGapType,
    SemanticJudgmentStatus,
    SourceType,
    ValidationStatus,
)
from marketpulse.investigation.domain.locators import EvidenceLocator
from marketpulse.investigation.harness.state_machine import Route


class AgentContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1", "2"] = "2"


class BudgetView(AgentContract):
    research_rounds_remaining: int = Field(default=0, ge=0)
    search_calls_remaining: int = Field(default=0, ge=0)
    fetch_calls_remaining: int = Field(default=0, ge=0)
    model_calls_remaining: int = Field(default=0, ge=0)
    tokens_remaining: int = Field(default=0, ge=0)
    sources_remaining: int = Field(default=0, ge=0)
    active_time_ms_remaining: int = Field(default=0, ge=0)


class CoverageView(AgentContract):
    valid_source_count: int = Field(default=0, ge=0)
    primary_official_count: int = Field(default=0, ge=0)
    independent_secondary_families: int = Field(default=0, ge=0)
    source_types: tuple[SourceType, ...] = ()
    family_summaries: tuple[str, ...] = ()
    failed_or_unreadable_sources: tuple[str, ...] = ()


class GapView(AgentContract):
    gap_key: str = Field(min_length=1)
    gap_type: ResearchGapType
    target_question_key: str | None = None
    target_claim_key: str | None = None
    reason: str = Field(min_length=1)
    missing_requirement: str | None = None
    suggested_action: str | None = None


class TaskSummaryView(AgentContract):
    task_key: str = Field(min_length=1)
    target_question_key: str | None = None
    purpose: str = Field(min_length=1)
    round: int = Field(ge=1)
    summary: str = Field(min_length=1)


class QuestionView(AgentContract):
    question_key: str = Field(min_length=1)
    text: str = Field(min_length=1)
    is_critical: bool = False


class TaskProposal(AgentContract):
    task_key: str = Field(min_length=1)
    target_question_key: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    priority: int = Field(ge=0, le=100)
    target_claim_key: str | None = None
    origin_gap_key: str | None = None
    purpose: str | None = None
    preferred_source_types: tuple[SourceType, ...] = ()
    desired_evidence_characteristics: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    suggested_queries: tuple[str, ...] = ()


class PlanInput(AgentContract):
    case_key: str = Field(min_length=1)
    scope_summary: str = Field(min_length=1)
    questions: tuple[QuestionView, ...]
    max_research_rounds: int = Field(ge=0)
    investigation_goal: str = "Not provided"
    event_description: str = "Not provided"
    critical_question_keys: tuple[str, ...] = ()
    coverage: CoverageView = Field(default_factory=CoverageView)
    unresolved_gaps: tuple[GapView, ...] = ()
    prior_task_summaries: tuple[TaskSummaryView, ...] = ()
    budget: BudgetView = Field(default_factory=BudgetView)


class PlanProposal(AgentContract):
    tasks: tuple[TaskProposal, ...]

    @model_validator(mode="after")
    def unique_tasks(self) -> PlanProposal:
        keys = [task.task_key for task in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("task keys must be unique")
        return self


class RouteInput(AgentContract):
    case_key: str = Field(min_length=1)
    gaps: tuple[GapView, ...]
    questions: tuple[QuestionView, ...]
    coverage: CoverageView = Field(default_factory=CoverageView)
    prior_task_summaries: tuple[TaskSummaryView, ...] = ()
    budget: BudgetView = Field(default_factory=BudgetView)


class SourceFamilyView(AgentContract):
    family_key: str = Field(min_length=1)
    source_keys: tuple[str, ...]
    summary: str = Field(min_length=1)


class QuerySummaryView(AgentContract):
    normalized_query: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    result_summary: str = Field(min_length=1)


class ResearchInput(AgentContract):
    task: TaskProposal
    prior_source_hashes: tuple[str, ...] = ()
    open_gap_keys: tuple[str, ...] = ()
    remaining_search_calls: int = Field(ge=0)
    target_question: QuestionView | None = None
    coverage: CoverageView = Field(default_factory=CoverageView)
    source_families: tuple[SourceFamilyView, ...] = ()
    executed_queries: tuple[QuerySummaryView, ...] = ()
    relevant_gaps: tuple[GapView, ...] = ()
    budget: BudgetView = Field(default_factory=BudgetView)
    round: int = Field(default=1, ge=1)


class QueryIntent(AgentContract):
    query_key: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=2000)
    target_question_key: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)
    expected_source_type: SourceType | None = None
    desired_source_role: Literal["PRIMARY", "SECONDARY", "EITHER"] = "EITHER"
    source_or_domain_hints: tuple[str, ...] = ()


class ResearchProposal(AgentContract):
    queries: tuple[QueryIntent, ...]
    stopping_suggestion: str | None = None
    stop_after_queries: bool = False


class ArtifactView(AgentContract):
    artifact_key: str = Field(min_length=1)
    snapshot_key: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1)
    locator: EvidenceLocator
    source_key: str = "unknown-source"
    source_title: str = "Unknown source"
    source_type: SourceType = SourceType.OTHER
    is_official: bool = False
    is_first_hand: bool = False
    trust_boundary: Literal["UNTRUSTED_SOURCE_DATA"] = "UNTRUSTED_SOURCE_DATA"


class ExistingClaimView(AgentContract):
    claim_key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    claim_type: ClaimType
    qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    status: ValidationStatus


class AnalysisInput(AgentContract):
    artifacts: tuple[ArtifactView, ...]
    prior_claim_keys: tuple[str, ...] = ()
    target_question: QuestionView | None = None
    existing_claims: tuple[ExistingClaimView, ...] = ()
    open_gaps: tuple[GapView, ...] = ()
    max_candidate_evidence: int = Field(default=20, ge=1, le=100)
    max_candidate_claims: int = Field(default=10, ge=1, le=50)


class EvidenceCandidate(AgentContract):
    evidence_key: str = Field(min_length=1)
    artifact_key: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator: EvidenceLocator
    quote_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AtomicityProposal(AgentContract):
    is_atomic: bool
    issues: tuple[str, ...] = ()
    proposed_atomic_statements: tuple[str, ...] = ()


class ClaimCandidate(AgentContract):
    claim_key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    claim_type: ClaimType
    supporting_evidence_keys: tuple[str, ...] = ()
    contradicting_evidence_keys: tuple[str, ...] = ()
    canonical_statement: str | None = None
    entity_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    time_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    scope_qualifiers: dict[str, JsonValue] = Field(default_factory=dict)
    importance: ClaimImportance = ClaimImportance.MEDIUM
    critical: bool = False
    atomicity: AtomicityProposal = Field(default_factory=lambda: AtomicityProposal(is_atomic=True))


class CandidateRelation(AgentContract):
    claim_key: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    stance: RelationStance


class TimelineCandidate(AgentContract):
    timeline_key: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_keys: tuple[str, ...] = ()
    event_time: str | None = None


class ConflictObservationCandidate(AgentContract):
    claim_key: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    conflict_type: ConflictType
    numeric_value: float | None = None
    unit: str | None = None
    report_time: str | None = None
    scope: str | None = None
    definition: str | None = None
    methodology: str | None = None
    report_stage: Literal["PRELIMINARY", "INTERIM", "FINAL", "UNKNOWN"] = "UNKNOWN"
    directness: float = Field(default=0.5, ge=0, le=1)
    specificity: float = Field(default=0.5, ge=0, le=1)


class AnalysisProposal(AgentContract):
    evidence: tuple[EvidenceCandidate, ...] = ()
    claims: tuple[ClaimCandidate, ...] = ()
    relations: tuple[CandidateRelation, ...] = ()
    timeline_events: tuple[TimelineCandidate, ...] = ()
    conflict_observations: tuple[ConflictObservationCandidate, ...] = ()

    @model_validator(mode="after")
    def references_are_local(self) -> AnalysisProposal:
        evidence_keys = [item.evidence_key for item in self.evidence]
        claim_keys = [item.claim_key for item in self.claims]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("evidence keys must be unique")
        if len(claim_keys) != len(set(claim_keys)):
            raise ValueError("claim keys must be unique")
        known = set(evidence_keys)
        for claim in self.claims:
            if (
                set(claim.supporting_evidence_keys) | set(claim.contradicting_evidence_keys)
            ) - known:
                raise ValueError("claim refers to unknown evidence candidate")
        for relation in self.relations:
            if relation.claim_key not in set(claim_keys) or relation.evidence_key not in known:
                raise ValueError("relation references an unknown claim or evidence candidate")
        for observation in self.conflict_observations:
            if (
                observation.claim_key not in set(claim_keys)
                or observation.evidence_key not in known
            ):
                raise ValueError("conflict observation references an unknown candidate")
        return self


class ClaimDecompositionInput(AgentContract):
    composite_claim: ClaimCandidate
    target_question: QuestionView | None = None


class ClaimDecompositionProposal(AgentContract):
    subclaims: tuple[ClaimCandidate, ...]

    @model_validator(mode="after")
    def subclaims_are_atomic(self) -> ClaimDecompositionProposal:
        if not self.subclaims:
            raise ValueError("decomposition must contain at least one subclaim")
        if any(not item.atomicity.is_atomic for item in self.subclaims):
            raise ValueError("decomposition repair must return atomic subclaims")
        return self


class VerificationInput(AgentContract):
    claims: tuple[ClaimCandidate, ...]
    evidence: tuple[EvidenceCandidate, ...]
    source_independence_keys: tuple[str, ...] = ()
    source_families: tuple[SourceFamilyView, ...] = ()
    existing_conflict_summaries: tuple[str, ...] = ()
    profile_expectations: tuple[str, ...] = ()
    target_claim_type: ClaimType | None = None


class SemanticJudgment(AgentContract):
    claim_key: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    entailment: SemanticJudgmentStatus
    rationale: str = Field(min_length=1)
    semantic_confidence: float = Field(default=0.5, ge=0, le=1)


class GapProposal(AgentContract):
    gap_key: str = Field(min_length=1)
    gap_type: ResearchGapType
    target_claim_key: str | None = None
    reason: str = Field(min_length=1)
    target_question_key: str | None = None
    preferred_source_type: SourceType | None = None
    missing_requirement: str | None = None
    suggested_action: str | None = None


class ContradictionInterpretation(AgentContract):
    claim_key: str = Field(min_length=1)
    evidence_keys: tuple[str, ...]
    interpretation: str = Field(min_length=1)


class ConflictExplanation(AgentContract):
    conflict_key: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    resolution_dimension: Literal["TIME", "SCOPE", "DEFINITION", "METHODOLOGY", "UNKNOWN"]


class VerificationProposal(AgentContract):
    judgments: tuple[SemanticJudgment, ...] = ()
    gaps: tuple[GapProposal, ...] = ()
    contradiction_interpretations: tuple[ContradictionInterpretation, ...] = ()
    conflict_explanations: tuple[ConflictExplanation, ...] = ()
    suggested_research_directions: tuple[str, ...] = ()


class RouteProposal(AgentContract):
    route: Route
    gap_keys: tuple[str, ...] = ()
    tasks: tuple[TaskProposal, ...] = ()
    reason: str | None = None


class ValidatedClaimView(AgentContract):
    claim_key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    status: Literal[
        ValidationStatus.VERIFIED,
        ValidationStatus.PROBABLE,
        ValidationStatus.DISPUTED,
        ValidationStatus.UNVERIFIED,
    ]
    evidence_keys: tuple[str, ...] = ()


class WriterInput(AgentContract):
    claims: tuple[ValidatedClaimView, ...]


class SectionDraft(AgentContract):
    section_key: str = Field(min_length=1)
    prose: str = Field(min_length=1)
    claim_keys: tuple[str, ...] = ()


class WriterProposal(AgentContract):
    sections: tuple[SectionDraft, ...]


class SourceStatistics(AgentContract):
    valid_sources: int = Field(ge=0)
    primary_official_sources: int = Field(ge=0)
    independent_families: int = Field(ge=0)
    source_types: tuple[SourceType, ...] = ()


class InvestigationSummary(AgentContract):
    run_key: str = Field(min_length=1)
    termination_reason: str = Field(min_length=1)
    verified_claims: tuple[ValidatedClaimView, ...] = ()
    probable_claims: tuple[ValidatedClaimView, ...] = ()
    disputed_claims: tuple[ValidatedClaimView, ...] = ()
    unverified_claims: tuple[ValidatedClaimView, ...] = ()
    timeline_event_keys: tuple[str, ...] = ()
    conflict_keys: tuple[str, ...] = ()
    research_gap_keys: tuple[str, ...] = ()
    source_statistics: SourceStatistics
    limitations: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()


class ReportInput(AgentContract):
    summary: InvestigationSummary


class SupervisorPort(Protocol):
    async def plan(self, request: PlanInput) -> PlanProposal: ...

    async def route(self, request: RouteInput) -> RouteProposal: ...


class ResearcherPort(Protocol):
    async def research(self, request: ResearchInput) -> ResearchProposal: ...


class AnalystPort(Protocol):
    async def analyze(self, request: AnalysisInput) -> AnalysisProposal: ...

    async def decompose(self, request: ClaimDecompositionInput) -> ClaimDecompositionProposal: ...


class VerifierPort(Protocol):
    async def verify(self, request: VerificationInput) -> VerificationProposal: ...


class WriterPort(Protocol):
    async def draft(self, request: WriterInput) -> WriterProposal: ...


def validate_agent_proposal(request: AgentContract, proposal: AgentContract) -> None:
    """Cross-check references against the exact bounded input shown to an Agent."""
    if isinstance(request, PlanInput) and isinstance(proposal, PlanProposal):
        questions = {item.question_key for item in request.questions}
        critical = {item.question_key for item in request.questions if item.is_critical}
        targets = {task.target_question_key for task in proposal.tasks}
        if not targets <= questions or not critical <= targets:
            raise ValueError("plan targets unknown questions or omits a critical question")
    elif isinstance(request, ResearchInput) and isinstance(proposal, ResearchProposal):
        if len(proposal.queries) > request.remaining_search_calls:
            raise ValueError("research proposal exceeds remaining search budget")
        keys = [item.query_key for item in proposal.queries]
        if len(keys) != len(set(keys)):
            raise ValueError("query keys must be unique")
        if any(
            item.target_question_key != request.task.target_question_key
            for item in proposal.queries
        ):
            raise ValueError("research query targets another question")
    elif isinstance(request, AnalysisInput) and isinstance(proposal, AnalysisProposal):
        artifacts = {item.artifact_key for item in request.artifacts}
        if any(item.artifact_key not in artifacts for item in proposal.evidence):
            raise ValueError("analysis references an artifact outside its input")
    elif isinstance(request, VerificationInput) and isinstance(proposal, VerificationProposal):
        claims = {item.claim_key for item in request.claims}
        evidence = {item.evidence_key for item in request.evidence}
        for item in proposal.judgments:
            if item.claim_key not in claims or item.evidence_key not in evidence:
                raise ValueError("verification references an unknown claim or evidence")
        if any(
            item.target_claim_key is not None and item.target_claim_key not in claims
            for item in proposal.gaps
        ):
            raise ValueError("verification gap targets an unknown claim")
    elif isinstance(request, RouteInput) and isinstance(proposal, RouteProposal):
        gaps = {item.gap_key for item in request.gaps}
        questions = {item.question_key for item in request.questions}
        if set(proposal.gap_keys) - gaps:
            raise ValueError("route references an unknown gap")
        if any(task.target_question_key not in questions for task in proposal.tasks):
            raise ValueError("follow-up task targets an unknown question")
        if any(
            task.origin_gap_key is not None and task.origin_gap_key not in gaps
            for task in proposal.tasks
        ):
            raise ValueError("follow-up task references an unknown origin gap")
    elif isinstance(request, WriterInput) and isinstance(proposal, WriterProposal):
        claims = {item.claim_key for item in request.claims}
        section_keys = [item.section_key for item in proposal.sections]
        if len(section_keys) != len(set(section_keys)):
            raise ValueError("section keys must be unique")
        if any(set(item.claim_keys) - claims for item in proposal.sections):
            raise ValueError("writer cites a claim outside its validated input")


def route_for_verification(proposal: VerificationProposal) -> Route:
    gap_types = {gap.gap_type for gap in proposal.gaps}
    if gap_types & {
        ResearchGapType.EVIDENCE_GAP,
        ResearchGapType.SOURCE_CONFLICT,
        ResearchGapType.UNREADABLE_SOURCE,
        ResearchGapType.MISSING_PRIMARY_SOURCE,
        ResearchGapType.INSUFFICIENT_INDEPENDENCE,
    }:
        return Route.COLLECT
    if ResearchGapType.ANALYSIS_ERROR in gap_types:
        return Route.ANALYZE
    if proposal.gaps:
        return Route.COLLECT
    return Route.READY_FOR_REPORT
