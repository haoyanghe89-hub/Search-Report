from __future__ import annotations

import json
from typing import Any, TypeVar, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.base import DomainModel
from marketpulse.investigation.domain.claims import (
    Claim,
    ClaimEvidenceRelation,
    ConflictSet,
    ResearchGap,
    TimelineEvent,
    ValidationResult,
)
from marketpulse.investigation.domain.enums import ExternalCallStatus, LocatorType
from marketpulse.investigation.domain.locators import deserialize_locator
from marketpulse.investigation.domain.recordings import RecordedModelCall, RecordedToolCall
from marketpulse.investigation.domain.reports import (
    AuditEvent,
    Report,
    ReportSection,
    ReviewDecision,
)
from marketpulse.investigation.domain.runtime import (
    CallBinding,
    ExecutionStep,
    Investigation,
    InvestigationQuestion,
    InvestigationRun,
    InvestigationScope,
    ResearchTask,
    RunBudget,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.persistence.models import (
    AuditEventRow,
    CallBindingRow,
    ClaimEvidenceRelationRow,
    ClaimRow,
    ConflictClaimRow,
    ConflictSetRow,
    DocumentArtifactRow,
    EvidenceRow,
    ExecutionStepRow,
    InvestigationQuestionRow,
    InvestigationRow,
    InvestigationRunRow,
    RecordedModelCallRow,
    RecordedToolCallRow,
    ReportRow,
    ReportSectionClaimRow,
    ReportSectionRow,
    ResearchGapRow,
    ResearchTaskRow,
    ReviewDecisionRow,
    RunBudgetRow,
    SourceRow,
    SourceSnapshotRow,
    TimelineEventRow,
    TimelineEvidenceRow,
    ValidationResultRow,
)

PersistedEntity = (
    Investigation
    | InvestigationRun
    | ExecutionStep
    | RunBudget
    | CallBinding
    | ResearchTask
    | Source
    | SourceSnapshot
    | DocumentArtifact
    | Evidence
    | Claim
    | ClaimEvidenceRelation
    | ConflictSet
    | ValidationResult
    | ResearchGap
    | TimelineEvent
    | Report
    | ReportSection
    | ReviewDecision
    | AuditEvent
    | RecordedToolCall
    | RecordedModelCall
)
T = TypeVar("T", bound=DomainModel)
RowT = TypeVar("RowT")


def _plain(model: DomainModel, *exclude: str) -> dict[str, object]:
    return model.model_dump(exclude=set(exclude))


class InvestigationRepository:
    """Explicit Investigation aggregate persistence; no legacy compatibility behavior."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def add(self, entity: PersistedEntity) -> None:
        with self._sessions.begin() as session:
            self.add_in_session(session, entity)

    def add_in_session(self, session: Session, entity: PersistedEntity) -> None:
        """CRUD only; the caller owns the transaction and commit."""
        row, related = self._to_rows(entity)
        session.add(row)
        session.flush()
        session.add_all(related)

    def get_in_session(self, session: Session, entity_type: type[T], entity_id: str) -> T:
        return cast(T, self._get(session, entity_type, entity_id))

    def binding_for_site(
        self,
        session: Session,
        run_id: str,
        logical_step_key: str,
        call_site_key: str,
        call_ordinal: int,
    ) -> CallBinding | None:
        row = session.scalar(
            select(CallBindingRow).where(
                CallBindingRow.run_id == run_id,
                CallBindingRow.logical_step_key == logical_step_key,
                CallBindingRow.call_site_key == call_site_key,
                CallBindingRow.call_ordinal == call_ordinal,
            )
        )
        return CallBinding.model_validate(self._row_dict(row)) if row else None

    def recorded_call_count(
        self, *, run_id: str, operation: str, fingerprint: str, kind: str
    ) -> int:
        row_type = RecordedModelCallRow if kind == "MODEL" else RecordedToolCallRow
        with self._sessions() as session:
            count = session.scalar(
                select(func.count())
                .select_from(row_type)
                .where(
                    row_type.run_id == run_id,
                    row_type.operation == operation,
                    row_type.request_fingerprint == fingerprint,
                )
            )
        return int(count or 0)

    def steps_for_run(self, session: Session, run_id: str) -> list[ExecutionStep]:
        rows = session.scalars(
            select(ExecutionStepRow)
            .where(ExecutionStepRow.run_id == run_id)
            .order_by(ExecutionStepRow.started_at, ExecutionStepRow.step_id)
        ).all()
        return [ExecutionStep.model_validate(self._row_dict(row)) for row in rows]

    def add_snapshot_bundle(
        self,
        snapshot: SourceSnapshot,
        artifacts: tuple[DocumentArtifact, ...],
        gaps: tuple[ResearchGap, ...] = (),
    ) -> None:
        """Commit one immutable parse outcome without an intermediate Snapshot state."""
        with self._sessions.begin() as session:
            snapshot_row, snapshot_related = self._to_rows(snapshot)
            session.add(snapshot_row)
            session.add_all(snapshot_related)
            session.flush()
            entities: tuple[PersistedEntity, ...] = (*artifacts, *gaps)
            for entity in entities:
                row, related = self._to_rows(entity)
                session.add(row)
                session.add_all(related)

    def source_by_url(self, investigation_id: str, canonical_url: str) -> Source | None:
        with self._sessions() as session:
            row = session.scalar(
                select(SourceRow).where(
                    SourceRow.investigation_id == investigation_id,
                    SourceRow.canonical_url == canonical_url,
                )
            )
            return Source.model_validate(self._row_dict(row)) if row else None

    def list_artifacts(self, snapshot_id: str) -> list[DocumentArtifact]:
        with self._sessions() as session:
            rows = session.scalars(
                select(DocumentArtifactRow)
                .where(DocumentArtifactRow.snapshot_id == snapshot_id)
                .order_by(DocumentArtifactRow.page_number, DocumentArtifactRow.artifact_id)
            ).all()
            return [self._document_artifact(row) for row in rows]

    def get(self, entity_type: type[T], entity_id: str) -> T:
        with self._sessions() as session:
            entity = self._get(session, entity_type, entity_id)
        return cast(T, entity)

    def list_validation_results(self, claim_id: str) -> list[ValidationResult]:
        with self._sessions() as session:
            rows = session.scalars(
                select(ValidationResultRow)
                .where(ValidationResultRow.claim_id == claim_id)
                .order_by(ValidationResultRow.created_at, ValidationResultRow.validation_id)
            ).all()
            return [self._validation(row) for row in rows]

    def list_audit_events(self, investigation_id: str) -> list[AuditEvent]:
        with self._sessions() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.investigation_id == investigation_id)
                .order_by(AuditEventRow.created_at, AuditEventRow.audit_event_id)
            ).all()
            return [self._audit(row) for row in rows]

    def list_replayable_tool_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedToolCall]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RecordedToolCallRow)
                .where(
                    RecordedToolCallRow.run_id == run_id,
                    RecordedToolCallRow.operation == operation,
                    RecordedToolCallRow.request_fingerprint == request_fingerprint,
                    RecordedToolCallRow.status == ExternalCallStatus.SUCCESS,
                    RecordedToolCallRow.replayable.is_(True),
                )
                .order_by(RecordedToolCallRow.recorded_at, RecordedToolCallRow.call_id)
            ).all()
            return [self._recorded_tool_call(row) for row in rows]

    def list_replayable_model_calls(
        self, *, run_id: str, operation: str, request_fingerprint: str
    ) -> list[RecordedModelCall]:
        with self._sessions() as session:
            rows = session.scalars(
                select(RecordedModelCallRow)
                .where(
                    RecordedModelCallRow.run_id == run_id,
                    RecordedModelCallRow.operation == operation,
                    RecordedModelCallRow.request_fingerprint == request_fingerprint,
                    RecordedModelCallRow.status == ExternalCallStatus.SUCCESS,
                    RecordedModelCallRow.replayable.is_(True),
                )
                .order_by(RecordedModelCallRow.recorded_at, RecordedModelCallRow.call_id)
            ).all()
            return [self._recorded_model_call(row) for row in rows]

    def _to_rows(self, entity: PersistedEntity) -> tuple[object, list[object]]:
        if isinstance(entity, Investigation):
            row = InvestigationRow(
                investigation_id=entity.investigation_id,
                title=entity.title,
                event_description=entity.event_description,
                investigation_goal=entity.investigation_goal,
                scope=entity.scope.model_dump(mode="json"),
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
            questions: list[object] = [
                InvestigationQuestionRow(
                    question_id=question.question_id,
                    investigation_id=entity.investigation_id,
                    text=question.text,
                    is_critical=question.is_critical,
                )
                for question in entity.questions
            ]
            return row, questions
        if isinstance(entity, InvestigationRun):
            return InvestigationRunRow(**_plain(entity)), []
        if isinstance(entity, ExecutionStep):
            payload = _plain(entity)
            payload["output_refs"] = list(entity.output_refs)
            payload["dependency_keys"] = list(entity.dependency_keys)
            payload["logical_step_key"] = entity.logical_step_key or entity.step_id
            return ExecutionStepRow(**payload), []
        if isinstance(entity, RunBudget):
            return RunBudgetRow(**_plain(entity)), []
        if isinstance(entity, CallBinding):
            return CallBindingRow(**_plain(entity)), []
        if isinstance(entity, ResearchTask):
            payload = _plain(entity)
            payload["query_hints"] = list(entity.query_hints)
            return ResearchTaskRow(**payload), []
        if isinstance(entity, Source):
            payload = _plain(entity)
            payload["canonical_url"] = str(entity.canonical_url)
            return SourceRow(**payload), []
        if isinstance(entity, SourceSnapshot):
            payload = _plain(entity, "raw_blob_ref", "cleaned_blob_ref")
            payload["raw_blob_ref"] = entity.raw_blob_ref.uri
            payload["cleaned_blob_ref"] = (
                entity.cleaned_blob_ref.uri if entity.cleaned_blob_ref else None
            )
            return SourceSnapshotRow(**payload), []
        if isinstance(entity, DocumentArtifact):
            payload = _plain(entity, "blob_ref")
            payload["blob_ref"] = entity.blob_ref.uri
            return DocumentArtifactRow(**payload), []
        if isinstance(entity, Evidence):
            payload = _plain(entity, "locator")
            payload["locator_type"] = LocatorType(entity.locator.locator_type)
            payload["locator_payload"] = entity.locator.model_dump(mode="json")
            return EvidenceRow(**payload), []
        if isinstance(entity, Claim):
            return ClaimRow(**_plain(entity)), []
        if isinstance(entity, ClaimEvidenceRelation):
            return ClaimEvidenceRelationRow(**_plain(entity)), []
        if isinstance(entity, ConflictSet):
            conflict_row = ConflictSetRow(**_plain(entity, "claim_ids"))
            conflict_claims: list[object] = [
                ConflictClaimRow(conflict_id=entity.conflict_id, claim_id=claim_id)
                for claim_id in entity.claim_ids
            ]
            return conflict_row, conflict_claims
        if isinstance(entity, ValidationResult):
            return ValidationResultRow(**_plain(entity)), []
        if isinstance(entity, ResearchGap):
            payload = _plain(entity)
            payload["suggested_actions"] = list(entity.suggested_actions)
            return ResearchGapRow(**payload), []
        if isinstance(entity, TimelineEvent):
            payload = _plain(entity, "supporting_evidence_ids")
            payload["related_entity_ids"] = list(entity.related_entity_ids)
            timeline_row = TimelineEventRow(**payload)
            timeline_evidence: list[object] = [
                TimelineEvidenceRow(
                    timeline_event_id=entity.timeline_event_id, evidence_id=evidence_id
                )
                for evidence_id in entity.supporting_evidence_ids
            ]
            return timeline_row, timeline_evidence
        if isinstance(entity, Report):
            return ReportRow(**_plain(entity)), []
        if isinstance(entity, ReportSection):
            payload = _plain(entity, "content_blob_ref", "claim_ids")
            payload["content_blob_ref"] = (
                entity.content_blob_ref.uri if entity.content_blob_ref else None
            )
            section_row = ReportSectionRow(**payload)
            section_claims: list[object] = [
                ReportSectionClaimRow(section_id=entity.section_id, claim_id=claim_id)
                for claim_id in entity.claim_ids
            ]
            return section_row, section_claims
        if isinstance(entity, ReviewDecision):
            return ReviewDecisionRow(**_plain(entity)), []
        if isinstance(entity, AuditEvent):
            payload = _plain(entity, "metadata")
            payload["metadata_payload"] = entity.metadata
            return AuditEventRow(**payload), []
        if isinstance(entity, RecordedToolCall):
            payload = _plain(entity, "request_blob_ref", "response_blob_ref", "metadata")
            payload.update(
                request_blob_ref=entity.request_blob_ref.uri,
                response_blob_ref=(
                    entity.response_blob_ref.uri if entity.response_blob_ref else None
                ),
                metadata_payload=entity.metadata,
            )
            return RecordedToolCallRow(**payload), []
        if isinstance(entity, RecordedModelCall):
            payload = _plain(entity, "request_blob_ref", "response_blob_ref", "metadata")
            payload.update(
                request_blob_ref=entity.request_blob_ref.uri,
                response_blob_ref=(
                    entity.response_blob_ref.uri if entity.response_blob_ref else None
                ),
                metadata_payload=entity.metadata,
            )
            return RecordedModelCallRow(**payload), []
        raise TypeError(f"unsupported investigation entity: {type(entity).__name__}")

    def _get(self, session: Session, entity_type: type[T], entity_id: str) -> PersistedEntity:
        row: Any
        if entity_type is Investigation:
            row = self._required(session, InvestigationRow, entity_id)
            questions = session.scalars(
                select(InvestigationQuestionRow)
                .where(InvestigationQuestionRow.investigation_id == entity_id)
                .order_by(InvestigationQuestionRow.question_id)
            ).all()
            items = tuple(
                InvestigationQuestion(
                    question_id=item.question_id,
                    text=item.text,
                    is_critical=item.is_critical,
                )
                for item in questions
            )
            return Investigation(
                investigation_id=row.investigation_id,
                title=row.title,
                event_description=row.event_description,
                investigation_goal=row.investigation_goal,
                scope=InvestigationScope.model_validate(row.scope),
                questions=items,
                critical_question_ids=tuple(
                    item.question_id for item in questions if item.is_critical
                ),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        if entity_type is InvestigationRun:
            return InvestigationRun.model_validate(
                self._row_dict(self._required(session, InvestigationRunRow, entity_id))
            )
        if entity_type is ExecutionStep:
            return ExecutionStep.model_validate(
                self._row_dict(self._required(session, ExecutionStepRow, entity_id))
            )
        if entity_type is RunBudget:
            return RunBudget.model_validate(
                self._row_dict(self._required(session, RunBudgetRow, entity_id))
            )
        if entity_type is CallBinding:
            return CallBinding.model_validate(
                self._row_dict(self._required(session, CallBindingRow, entity_id))
            )
        if entity_type is ResearchTask:
            return ResearchTask.model_validate(
                self._row_dict(self._required(session, ResearchTaskRow, entity_id))
            )
        if entity_type is Source:
            return Source.model_validate(
                self._row_dict(self._required(session, SourceRow, entity_id))
            )
        if entity_type is SourceSnapshot:
            row = self._required(session, SourceSnapshotRow, entity_id)
            payload = self._row_dict(row)
            payload["raw_blob_ref"] = BlobRef.from_uri(row.raw_blob_ref)
            payload["cleaned_blob_ref"] = (
                BlobRef.from_uri(row.cleaned_blob_ref) if row.cleaned_blob_ref else None
            )
            return SourceSnapshot.model_validate(payload)
        if entity_type is DocumentArtifact:
            return self._document_artifact(self._required(session, DocumentArtifactRow, entity_id))
        if entity_type is Evidence:
            row = self._required(session, EvidenceRow, entity_id)
            payload = self._row_dict(row, "locator_type", "locator_payload")
            payload["locator"] = deserialize_locator(
                json.dumps(row.locator_payload, sort_keys=True, separators=(",", ":"))
            )
            return Evidence.model_validate(payload)
        if entity_type is Claim:
            return Claim.model_validate(
                self._row_dict(self._required(session, ClaimRow, entity_id))
            )
        if entity_type is ClaimEvidenceRelation:
            return ClaimEvidenceRelation.model_validate(
                self._row_dict(self._required(session, ClaimEvidenceRelationRow, entity_id))
            )
        if entity_type is ConflictSet:
            row = self._required(session, ConflictSetRow, entity_id)
            claim_ids = session.scalars(
                select(ConflictClaimRow.claim_id)
                .where(ConflictClaimRow.conflict_id == entity_id)
                .order_by(ConflictClaimRow.claim_id)
            ).all()
            payload = self._row_dict(row)
            payload["claim_ids"] = tuple(claim_ids)
            return ConflictSet.model_validate(payload)
        if entity_type is ValidationResult:
            return self._validation(self._required(session, ValidationResultRow, entity_id))
        if entity_type is ResearchGap:
            return ResearchGap.model_validate(
                self._row_dict(self._required(session, ResearchGapRow, entity_id))
            )
        if entity_type is TimelineEvent:
            row = self._required(session, TimelineEventRow, entity_id)
            evidence_ids = session.scalars(
                select(TimelineEvidenceRow.evidence_id)
                .where(TimelineEvidenceRow.timeline_event_id == entity_id)
                .order_by(TimelineEvidenceRow.evidence_id)
            ).all()
            payload = self._row_dict(row)
            payload["supporting_evidence_ids"] = tuple(evidence_ids)
            return TimelineEvent.model_validate(payload)
        if entity_type is Report:
            return Report.model_validate(
                self._row_dict(self._required(session, ReportRow, entity_id))
            )
        if entity_type is ReportSection:
            row = self._required(session, ReportSectionRow, entity_id)
            claim_ids = session.scalars(
                select(ReportSectionClaimRow.claim_id)
                .where(ReportSectionClaimRow.section_id == entity_id)
                .order_by(ReportSectionClaimRow.claim_id)
            ).all()
            payload = self._row_dict(row)
            payload["content_blob_ref"] = (
                BlobRef.from_uri(row.content_blob_ref) if row.content_blob_ref else None
            )
            payload["claim_ids"] = tuple(claim_ids)
            return ReportSection.model_validate(payload)
        if entity_type is ReviewDecision:
            return ReviewDecision.model_validate(
                self._row_dict(self._required(session, ReviewDecisionRow, entity_id))
            )
        if entity_type is AuditEvent:
            return self._audit(self._required(session, AuditEventRow, entity_id))
        if entity_type is RecordedToolCall:
            return self._recorded_tool_call(self._required(session, RecordedToolCallRow, entity_id))
        if entity_type is RecordedModelCall:
            return self._recorded_model_call(
                self._required(session, RecordedModelCallRow, entity_id)
            )
        raise TypeError(f"unsupported investigation entity type: {entity_type.__name__}")

    @staticmethod
    def _required(session: Session, row_type: type[RowT], entity_id: str) -> RowT:
        row = session.get(row_type, entity_id)
        if row is None:
            raise KeyError(entity_id)
        return row

    @staticmethod
    def _row_dict(row: object, *exclude: str) -> dict[str, object]:
        table = row.__table__  # type: ignore[attr-defined]
        excluded = set(exclude)
        return {
            column.key: getattr(row, column.key)
            for column in table.columns
            if column.key not in excluded
        }

    @classmethod
    def _recorded_tool_call(cls, row: RecordedToolCallRow) -> RecordedToolCall:
        payload = cls._row_dict(row, "metadata_payload")
        payload.update(
            request_blob_ref=BlobRef.from_uri(row.request_blob_ref),
            response_blob_ref=(
                BlobRef.from_uri(row.response_blob_ref) if row.response_blob_ref else None
            ),
            metadata=row.metadata_payload,
        )
        return RecordedToolCall.model_validate(payload)

    @classmethod
    def _document_artifact(cls, row: DocumentArtifactRow) -> DocumentArtifact:
        payload = cls._row_dict(row)
        payload["blob_ref"] = BlobRef.from_uri(row.blob_ref)
        return DocumentArtifact.model_validate(payload)

    @classmethod
    def _recorded_model_call(cls, row: RecordedModelCallRow) -> RecordedModelCall:
        payload = cls._row_dict(row, "metadata_payload")
        payload.update(
            request_blob_ref=BlobRef.from_uri(row.request_blob_ref),
            response_blob_ref=(
                BlobRef.from_uri(row.response_blob_ref) if row.response_blob_ref else None
            ),
            metadata=row.metadata_payload,
        )
        return RecordedModelCall.model_validate(payload)

    def _validation(self, row: ValidationResultRow) -> ValidationResult:
        return ValidationResult.model_validate(self._row_dict(row))

    def _audit(self, row: AuditEventRow) -> AuditEvent:
        payload = self._row_dict(row, "metadata_payload")
        payload["metadata"] = row.metadata_payload
        return AuditEvent.model_validate(payload)
