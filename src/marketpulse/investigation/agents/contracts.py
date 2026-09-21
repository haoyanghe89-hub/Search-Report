from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marketpulse.investigation.domain.enums import (
    ClaimType,
    EntailmentStatus,
    ResearchGapType,
    ValidationStatus,
)
from marketpulse.investigation.domain.locators import EvidenceLocator
from marketpulse.investigation.harness.state_machine import Route


class AgentContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contract_version: Literal["1"] = "1"


class QuestionView(AgentContract):
    question_key: str = Field(min_length=1)
    text: str = Field(min_length=1)
    is_critical: bool = False


class TaskProposal(AgentContract):
    task_key: str = Field(min_length=1)
    target_question_key: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    priority: int = Field(ge=0, le=100)


class PlanInput(AgentContract):
    case_key: str = Field(min_length=1)
    scope_summary: str = Field(min_length=1)
    questions: tuple[QuestionView, ...]
    max_research_rounds: int = Field(ge=0)


class PlanProposal(AgentContract):
    tasks: tuple[TaskProposal, ...]

    @model_validator(mode="after")
    def unique_tasks(self) -> PlanProposal:
        keys = [task.task_key for task in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("task keys must be unique")
        return self


class ResearchInput(AgentContract):
    task: TaskProposal
    prior_source_hashes: tuple[str, ...] = ()
    open_gap_keys: tuple[str, ...] = ()
    remaining_search_calls: int = Field(ge=0)


class QueryIntent(AgentContract):
    query_key: str = Field(min_length=1)
    query: str = Field(min_length=1, max_length=2000)
    target_question_key: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=50)


class ResearchProposal(AgentContract):
    queries: tuple[QueryIntent, ...]


class ArtifactView(AgentContract):
    artifact_key: str = Field(min_length=1)
    snapshot_key: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1)
    locator: EvidenceLocator


class AnalysisInput(AgentContract):
    artifacts: tuple[ArtifactView, ...]
    prior_claim_keys: tuple[str, ...] = ()


class EvidenceCandidate(AgentContract):
    evidence_key: str = Field(min_length=1)
    artifact_key: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    locator: EvidenceLocator


class ClaimCandidate(AgentContract):
    claim_key: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    claim_type: ClaimType
    supporting_evidence_keys: tuple[str, ...] = ()
    contradicting_evidence_keys: tuple[str, ...] = ()


class AnalysisProposal(AgentContract):
    evidence: tuple[EvidenceCandidate, ...] = ()
    claims: tuple[ClaimCandidate, ...] = ()

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
        return self


class VerificationInput(AgentContract):
    claims: tuple[ClaimCandidate, ...]
    evidence: tuple[EvidenceCandidate, ...]
    source_independence_keys: tuple[str, ...] = ()


class SemanticJudgment(AgentContract):
    claim_key: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    entailment: EntailmentStatus
    rationale: str = Field(min_length=1)


class GapProposal(AgentContract):
    gap_key: str = Field(min_length=1)
    gap_type: ResearchGapType
    target_claim_key: str | None = None
    reason: str = Field(min_length=1)


class VerificationProposal(AgentContract):
    judgments: tuple[SemanticJudgment, ...] = ()
    gaps: tuple[GapProposal, ...] = ()


class RouteProposal(AgentContract):
    route: Route
    gap_keys: tuple[str, ...] = ()


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


class SupervisorPort(Protocol):
    async def plan(self, request: PlanInput) -> PlanProposal: ...

    async def route(self, request: VerificationProposal) -> RouteProposal: ...


class ResearcherPort(Protocol):
    async def research(self, request: ResearchInput) -> ResearchProposal: ...


class AnalystPort(Protocol):
    async def analyze(self, request: AnalysisInput) -> AnalysisProposal: ...


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
    return Route.READY_FOR_REPORT
