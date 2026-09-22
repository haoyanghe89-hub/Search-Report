from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from marketpulse.investigation.agents.contracts import (
    AnalysisProposal,
    InvestigationSummary,
    ReportInput,
    ResearchProposal,
    VerificationProposal,
)
from marketpulse.investigation.domain.enums import ValidationStatus
from marketpulse.investigation.validation.models import ConflictObservation


class FeedbackModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FeedbackLoopConfig(FeedbackModel):
    workflow_version: str = "agent-feedback-v1"
    max_artifacts: int = Field(default=12, ge=1, le=100)
    max_excerpts: int = Field(default=24, ge=1, le=200)
    max_context_chars: int = Field(default=40_000, ge=1000)
    max_context_items: int = Field(default=100, ge=1, le=1000)
    max_verification_claims: int = Field(default=16, ge=1, le=100)
    max_verification_evidence: int = Field(default=64, ge=1, le=500)
    max_query_length: int = Field(default=500, ge=1, le=2000)
    no_progress_rounds: int = Field(default=2, ge=1, le=10)
    step_timeout_seconds: float = Field(default=120.0, gt=0)


class PhaseTransition(FeedbackModel):
    action: Literal["ENTER_PLAN", "BLOCK"]
    reason: str = Field(min_length=1)


class ResearchExecutionResult(FeedbackModel):
    proposal: ResearchProposal
    acquired_source_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    acquisition_gap_ids: tuple[str, ...] = ()
    valid_source_count: int = Field(default=0, ge=0)
    rejected_queries: tuple[str, ...] = ()


class AnalysisExecutionResult(FeedbackModel):
    proposal: AnalysisProposal
    evidence_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    reused_claim_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()
    timeline_event_ids: tuple[str, ...] = ()
    rejected_candidate_keys: tuple[str, ...] = ()
    conflict_observations: tuple[ConflictObservation, ...] = ()


class ClaimValidationSummary(FeedbackModel):
    claim_id: str
    validation_id: str
    status: ValidationStatus
    confidence: float = Field(ge=0, le=1)
    gap_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    semantic_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationExecutionResult(FeedbackModel):
    verifier_proposals: tuple[VerificationProposal, ...]
    validations: tuple[ClaimValidationSummary, ...]
    route_reason: str


class InformationGainSummary(FeedbackModel):
    round: int = Field(ge=1)
    new_valid_sources: int = Field(ge=0)
    new_independent_families: int = Field(ge=0)
    new_evidence: int = Field(ge=0)
    new_claims: int = Field(ge=0)
    resolved_gaps: int = Field(ge=0)
    new_gaps: int = Field(ge=0)
    resolved_conflicts: int = Field(ge=0)
    validation_improvements: tuple[str, ...] = ()
    validation_changes: tuple[str, ...] = ()

    @property
    def has_information_gain(self) -> bool:
        return any(
            (
                self.new_valid_sources,
                self.new_independent_families,
                self.new_evidence,
                self.new_claims,
                self.resolved_gaps,
                self.resolved_conflicts,
                len(self.validation_changes),
            )
        )


class RoundSnapshot(FeedbackModel):
    valid_source_ids: frozenset[str] = frozenset()
    family_ids: frozenset[str] = frozenset()
    evidence_ids: frozenset[str] = frozenset()
    claim_ids: frozenset[str] = frozenset()
    open_gap_ids: frozenset[str] = frozenset()
    resolved_conflict_ids: frozenset[str] = frozenset()
    validation_statuses: dict[str, ValidationStatus] = Field(default_factory=dict)


class FeedbackLoopResult(FeedbackModel):
    run_id: str
    termination: Literal["READY_FOR_REPORT", "BLOCKED", "FAILED"]
    reason: str
    rounds_completed: int = Field(ge=0)
    phase_trace: tuple[str, ...]
    information_gain: tuple[InformationGainSummary, ...]
    report_input: ReportInput

    @property
    def summary(self) -> InvestigationSummary:
        """Compatibility view for callers that consumed the pre-boundary summary."""
        return self.report_input.summary
