from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.persistence.models import (
    CallBindingRow,
    ClaimEvidenceRelationRow,
    ClaimRow,
    DocumentArtifactRow,
    EvidenceRow,
    RecordedModelCallRow,
    ResearchGapRow,
    ResearchTaskRow,
    SourceRow,
    SourceSnapshotRow,
    ValidationResultRow,
)


class TraceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvidenceSourceTrace(TraceModel):
    relation_id: str
    evidence_id: str
    snapshot_id: str
    artifact_id: str | None
    source_id: str
    canonical_url: str
    locator_payload: dict[str, object]
    analysis_step_id: str | None
    research_task_id: str | None


class ClaimTrace(TraceModel):
    claim_id: str
    validation_ids: tuple[str, ...]
    evidence_paths: tuple[EvidenceSourceTrace, ...]
    analysis_step_id: str | None
    research_task_id: str | None
    research_task_ids: tuple[str, ...]
    analyst_model_call_ids: tuple[str, ...]
    researcher_model_call_ids: tuple[str, ...]
    search_call_ids: tuple[str, ...]
    fetch_call_ids: tuple[str, ...]


class GapFollowupTrace(TraceModel):
    gap_id: str
    origin_validation_id: str | None
    followup_task_ids: tuple[str, ...]
    parent_task_ids: tuple[str, ...]


class TraceResolver:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def claim(self, claim_id: str) -> ClaimTrace:
        with self.sessions() as session:
            claim = session.get(ClaimRow, claim_id)
            if claim is None:
                raise KeyError(claim_id)
            validation_ids = tuple(
                session.scalars(
                    select(ValidationResultRow.validation_id)
                    .where(ValidationResultRow.claim_id == claim_id)
                    .order_by(ValidationResultRow.created_at)
                ).all()
            )
            rows = session.execute(
                select(
                    ClaimEvidenceRelationRow.relation_id,
                    EvidenceRow.evidence_id,
                    EvidenceRow.snapshot_id,
                    EvidenceRow.artifact_id,
                    SourceRow.source_id,
                    SourceRow.canonical_url,
                    EvidenceRow.locator_payload,
                    EvidenceRow.created_by_step_id,
                    EvidenceRow.research_task_id,
                )
                .join(EvidenceRow, EvidenceRow.evidence_id == ClaimEvidenceRelationRow.evidence_id)
                .join(
                    SourceSnapshotRow,
                    SourceSnapshotRow.snapshot_id == EvidenceRow.snapshot_id,
                )
                .join(SourceRow, SourceRow.source_id == SourceSnapshotRow.source_id)
                .outerjoin(
                    DocumentArtifactRow,
                    DocumentArtifactRow.artifact_id == EvidenceRow.artifact_id,
                )
                .where(ClaimEvidenceRelationRow.claim_id == claim_id)
                .order_by(ClaimEvidenceRelationRow.relation_id)
            ).all()
            evidence_paths = tuple(
                EvidenceSourceTrace(
                    relation_id=row.relation_id,
                    evidence_id=row.evidence_id,
                    snapshot_id=row.snapshot_id,
                    artifact_id=row.artifact_id,
                    source_id=row.source_id,
                    canonical_url=row.canonical_url,
                    locator_payload=row.locator_payload,
                    analysis_step_id=row.created_by_step_id,
                    research_task_id=row.research_task_id,
                )
                for row in rows
            )
            analysis_step_ids = {
                item
                for item in (
                    claim.created_by_step_id,
                    *(row.analysis_step_id for row in evidence_paths),
                )
                if item is not None
            }
            analyst = tuple(
                sorted(
                    {
                        call_id
                        for step_id in analysis_step_ids
                        for call_id in self._model_calls(session, step_id)
                    }
                )
            )
            task_ids = tuple(
                sorted(
                    {
                        item
                        for item in (
                            claim.research_task_id,
                            *(row.research_task_id for row in evidence_paths),
                        )
                        if item is not None
                    }
                )
            )
            tasks = tuple(
                task
                for task_id in task_ids
                if (task := session.get(ResearchTaskRow, task_id)) is not None
            )
            research_keys = tuple(f"research:{task.title}:round-{task.round}" for task in tasks)
            research_steps = self._bound_calls(
                session,
                run_id=claim.run_id,
                logical_step_keys=research_keys,
                operation="model.generate",
            )
            searches = self._bound_calls(
                session,
                run_id=claim.run_id,
                logical_step_keys=research_keys,
                operation="search",
            )
            fetches = self._bound_calls(
                session,
                run_id=claim.run_id,
                logical_step_keys=research_keys,
                operation="fetch",
            )
            return ClaimTrace(
                claim_id=claim_id,
                validation_ids=validation_ids,
                evidence_paths=evidence_paths,
                analysis_step_id=claim.created_by_step_id,
                research_task_id=claim.research_task_id,
                research_task_ids=task_ids,
                analyst_model_call_ids=analyst,
                researcher_model_call_ids=research_steps,
                search_call_ids=searches,
                fetch_call_ids=fetches,
            )

    def gap(self, gap_id: str) -> GapFollowupTrace:
        with self.sessions() as session:
            gap = session.get(ResearchGapRow, gap_id)
            if gap is None:
                raise KeyError(gap_id)
            tasks = session.scalars(
                select(ResearchTaskRow)
                .where(ResearchTaskRow.origin_gap_id == gap_id)
                .order_by(ResearchTaskRow.task_id)
            ).all()
            return GapFollowupTrace(
                gap_id=gap_id,
                origin_validation_id=gap.origin_validation_id,
                followup_task_ids=tuple(item.task_id for item in tasks),
                parent_task_ids=tuple(
                    item.parent_task_id for item in tasks if item.parent_task_id is not None
                ),
            )

    @staticmethod
    def _model_calls(session: Session, step_id: str | None) -> tuple[str, ...]:
        if step_id is None:
            return ()
        return tuple(
            session.scalars(
                select(RecordedModelCallRow.call_id)
                .where(RecordedModelCallRow.step_id == step_id)
                .order_by(RecordedModelCallRow.call_id)
            ).all()
        )

    @staticmethod
    def _bound_calls(
        session: Session,
        *,
        run_id: str,
        logical_step_keys: tuple[str, ...],
        operation: str,
    ) -> tuple[str, ...]:
        if not logical_step_keys:
            return ()
        return tuple(
            session.scalars(
                select(CallBindingRow.recorded_call_id)
                .where(
                    CallBindingRow.run_id == run_id,
                    CallBindingRow.logical_step_key.in_(logical_step_keys),
                    CallBindingRow.operation == operation,
                )
                .order_by(CallBindingRow.recorded_call_id)
            ).all()
        )
