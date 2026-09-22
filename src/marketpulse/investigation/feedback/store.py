from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
    ResearchGap,
    TimelineEvent,
    ValidationResult,
)
from marketpulse.investigation.domain.enums import GapStatus, ResearchTaskStatus
from marketpulse.investigation.domain.runtime import (
    ExecutionStep,
    Investigation,
    InvestigationRun,
    ResearchTask,
    RunBudget,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.harness.persistence import RunBudgetExceededError
from marketpulse.investigation.persistence.models import (
    ClaimEvidenceRelationRow,
    ClaimRow,
    ConflictSetRow,
    DocumentArtifactRow,
    EvidenceRow,
    ExecutionStepRow,
    ResearchGapRow,
    ResearchTaskRow,
    RunBudgetRow,
    SourceSnapshotRow,
    TimelineEventRow,
    ValidationResultRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class FeedbackState:
    investigation: Investigation
    run: InvestigationRun
    budget: RunBudget
    tasks: tuple[ResearchTask, ...]
    sources: tuple[Source, ...]
    snapshots: tuple[SourceSnapshot, ...]
    artifacts: tuple[DocumentArtifact, ...]
    evidence: tuple[Evidence, ...]
    claims: tuple[Claim, ...]
    relations: tuple[ClaimEvidenceRelation, ...]
    gaps: tuple[ResearchGap, ...]
    conflicts: tuple[ConflictSet, ...]
    validations: tuple[ValidationResult, ...]
    timeline_events: tuple[TimelineEvent, ...]
    steps: tuple[ExecutionStep, ...]


class FeedbackStore:
    """Read models and focused mutations for the Agent loop."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
    ) -> None:
        self.sessions = sessions
        self.repository = repository

    def state(self, run_id: str) -> FeedbackState:
        run = self.repository.get(InvestigationRun, run_id)
        snapshots = self._entities(SourceSnapshotRow, SourceSnapshot, "snapshot_id", run_id)
        return FeedbackState(
            investigation=self.repository.get(Investigation, run.investigation_id),
            run=run,
            budget=self.repository.get(RunBudget, run_id),
            tasks=self._entities(ResearchTaskRow, ResearchTask, "task_id", run_id),
            sources=self._sources(snapshots),
            snapshots=snapshots,
            artifacts=self._artifacts(run_id),
            evidence=self._entities(EvidenceRow, Evidence, "evidence_id", run_id),
            claims=self._entities(ClaimRow, Claim, "claim_id", run_id),
            relations=self._relations(run_id),
            gaps=self._entities(ResearchGapRow, ResearchGap, "gap_id", run_id),
            conflicts=self._entities(ConflictSetRow, ConflictSet, "conflict_id", run_id),
            validations=self._entities(
                ValidationResultRow, ValidationResult, "validation_id", run_id
            ),
            timeline_events=self._entities(
                TimelineEventRow, TimelineEvent, "timeline_event_id", run_id
            ),
            steps=self._entities(ExecutionStepRow, ExecutionStep, "step_id", run_id),
        )

    def pending_tasks(self, run_id: str) -> tuple[ResearchTask, ...]:
        return tuple(
            task for task in self.state(run_id).tasks if task.status is ResearchTaskStatus.PENDING
        )

    def latest_validations(self, state: FeedbackState) -> dict[str, ValidationResult]:
        latest: dict[str, ValidationResult] = {}
        for result in sorted(
            state.validations,
            key=lambda item: (item.created_at, item.validation_id),
        ):
            latest[result.claim_id] = result
        return latest

    def open_gaps(self, state: FeedbackState) -> tuple[ResearchGap, ...]:
        return tuple(gap for gap in state.gaps if gap.status is GapStatus.OPEN)

    def _entities(
        self,
        row_type: Any,
        entity_type: type[T],
        id_field: str,
        run_id: str,
    ) -> tuple[T, ...]:
        column = row_type.run_id
        order = getattr(row_type, id_field)
        with self.sessions() as session:
            ids = session.scalars(select(order).where(column == run_id).order_by(order)).all()
        return tuple(
            self.repository.get(entity_type, entity_id)  # type: ignore[type-var]
            for entity_id in ids
        )

    def _sources(self, snapshots: tuple[SourceSnapshot, ...]) -> tuple[Source, ...]:
        source_ids = sorted({item.source_id for item in snapshots})
        return tuple(self.repository.get(Source, source_id) for source_id in source_ids)

    def _artifacts(self, run_id: str) -> tuple[DocumentArtifact, ...]:
        with self.sessions() as session:
            ids = session.scalars(
                select(DocumentArtifactRow.artifact_id)
                .join(
                    SourceSnapshotRow,
                    SourceSnapshotRow.snapshot_id == DocumentArtifactRow.snapshot_id,
                )
                .where(SourceSnapshotRow.run_id == run_id)
                .order_by(DocumentArtifactRow.artifact_id)
            ).all()
        return tuple(self.repository.get(DocumentArtifact, item) for item in ids)

    def _relations(self, run_id: str) -> tuple[ClaimEvidenceRelation, ...]:
        with self.sessions() as session:
            ids = session.scalars(
                select(ClaimEvidenceRelationRow.relation_id)
                .join(ClaimRow, ClaimRow.claim_id == ClaimEvidenceRelationRow.claim_id)
                .where(ClaimRow.run_id == run_id)
                .order_by(ClaimEvidenceRelationRow.relation_id)
            ).all()
        return tuple(self.repository.get(ClaimEvidenceRelation, item) for item in ids)


@dataclass(frozen=True, slots=True)
class CompleteResearchTaskOperation:
    task_id: str
    query_hints: tuple[str, ...]
    completed_at: datetime

    def apply(self, session: Session, repository: InvestigationRepository) -> None:
        del repository
        row = session.get(ResearchTaskRow, self.task_id)
        if row is None:
            raise KeyError(self.task_id)
        row.status = ResearchTaskStatus.COMPLETED
        row.query_hints = list(self.query_hints)
        row.updated_at = self.completed_at
        row.completed_at = self.completed_at


@dataclass(frozen=True, slots=True)
class ReserveSourcesOperation:
    run_id: str
    count: int
    updated_at: datetime

    def apply(self, session: Session, repository: InvestigationRepository) -> None:
        del repository
        row = session.get(RunBudgetRow, self.run_id)
        if row is None:
            raise KeyError(self.run_id)
        if self.count < 0 or row.sources_used + self.count > row.max_sources:
            raise RunBudgetExceededError("source budget exhausted")
        row.sources_used += self.count
        row.updated_at = self.updated_at


@dataclass(frozen=True, slots=True)
class ResolveGapsOperation:
    gap_ids: tuple[str, ...]
    resolved_at: datetime

    def apply(self, session: Session, repository: InvestigationRepository) -> None:
        del repository
        for gap_id in self.gap_ids:
            row = session.get(ResearchGapRow, gap_id)
            if row is None:
                raise KeyError(gap_id)
            row.status = GapStatus.RESOLVED
            row.resolved_at = self.resolved_at
