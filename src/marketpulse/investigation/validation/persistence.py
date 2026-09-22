from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.investigation.domain.claims import ConflictSet, ValidationResult
from marketpulse.investigation.persistence.models import (
    ClaimRow,
    ConflictClaimRow,
    ConflictEvidenceRow,
    ConflictSetRow,
    SemanticJudgmentRow,
    SourceFamilyMemberRow,
    SourceFamilyRow,
    ValidationConflictRow,
    ValidationResultRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.validation.models import ValidationOutcome, ValidationRequest


class AppendOnlyValidationError(RuntimeError):
    pass


class ValidationPersistence:
    """Persists a validation envelope and Claim latest projection in one short transaction."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        repository: InvestigationRepository,
    ) -> None:
        self._sessions = sessions
        self._repository = repository

    def persist(
        self,
        *,
        request: ValidationRequest,
        outcome: ValidationOutcome,
    ) -> ValidationResult:
        with self._sessions.begin() as session:
            self.persist_in_session(session, self._repository, request=request, outcome=outcome)
        return self._repository.get(ValidationResult, outcome.result.validation_id)

    @classmethod
    def persist_in_session(
        cls,
        session: Session,
        repository: InvestigationRepository,
        *,
        request: ValidationRequest,
        outcome: ValidationOutcome,
    ) -> None:
        if request.validation_id != outcome.result.validation_id:
            raise ValueError("request and outcome validation IDs differ")
        if session.get(ValidationResultRow, outcome.result.validation_id) is not None:
            raise AppendOnlyValidationError("ValidationResult is append-only")
        claim_row = session.get(ClaimRow, outcome.result.claim_id)
        if claim_row is None:
            raise KeyError(outcome.result.claim_id)
        if claim_row.run_id != outcome.result.run_id:
            raise ValueError("ValidationResult and Claim belong to different Runs")

        cls._persist_semantic_judgments(session, request)
        for conflict in outcome.conflict_updates:
            cls._persist_conflict(session, repository, conflict)
        repository.add_in_session(session, outcome.result)
        session.add_all(
            ValidationConflictRow(
                validation_id=outcome.result.validation_id,
                conflict_id=conflict_id,
            )
            for conflict_id in outcome.result.conflict_set_refs
        )
        cls._persist_families(session, outcome)
        for gap in outcome.research_gaps:
            repository.add_in_session(session, gap)

        claim_row.validation_status = outcome.result.status
        claim_row.confidence = outcome.result.confidence
        claim_row.confidence_basis = outcome.result.confidence_basis
        claim_row.latest_validation_id = outcome.result.validation_id
        claim_row.updated_at = outcome.result.created_at

    def assert_latest_projection_consistent(self, claim_id: str) -> None:
        with self._sessions() as session:
            claim = session.get(ClaimRow, claim_id)
            if claim is None:
                raise KeyError(claim_id)
            latest = session.scalar(
                select(ValidationResultRow)
                .where(ValidationResultRow.claim_id == claim_id)
                .order_by(
                    ValidationResultRow.created_at.desc(),
                    ValidationResultRow.validation_id.desc(),
                )
                .limit(1)
            )
            if latest is None:
                if claim.latest_validation_id is not None:
                    raise AssertionError("Claim points to a missing ValidationResult")
                return
            if (
                claim.latest_validation_id != latest.validation_id
                or claim.validation_status != latest.status
                or claim.confidence != latest.confidence
                or claim.confidence_basis != latest.confidence_basis
            ):
                raise AssertionError("Claim latest-validation projection is inconsistent")

    @staticmethod
    def _persist_semantic_judgments(session: Session, request: ValidationRequest) -> None:
        for judgment in request.semantic_judgments:
            existing = session.get(SemanticJudgmentRow, judgment.judgment_id)
            payload = judgment.model_dump()
            if existing is None:
                session.add(SemanticJudgmentRow(**payload))
                continue
            immutable_fields = (
                "run_id",
                "claim_id",
                "evidence_id",
                "judgment",
                "reason",
                "semantic_confidence",
                "model_call_ref",
                "recorded_judgment_ref",
                "schema_version",
            )
            if any(getattr(existing, field) != payload[field] for field in immutable_fields):
                raise AppendOnlyValidationError("SemanticJudgment ID has different content")

    @staticmethod
    def _persist_conflict(
        session: Session,
        repository: InvestigationRepository,
        conflict: ConflictSet,
    ) -> None:
        row = session.get(ConflictSetRow, conflict.conflict_id)
        if row is None:
            repository.add_in_session(session, conflict)
            return
        row.conflict_type = conflict.conflict_type
        row.severity = conflict.severity
        row.status = conflict.status
        row.possible_causes = list(conflict.possible_causes)
        row.competing_values = list(conflict.competing_values)
        row.possible_explanations = list(conflict.possible_explanations)
        row.resolution_status = conflict.resolution_status
        row.resolution_basis = conflict.resolution_basis
        row.resolution_summary = conflict.resolution_summary
        row.updated_at = conflict.updated_at
        existing_claims = set(
            session.scalars(
                select(ConflictClaimRow.claim_id).where(
                    ConflictClaimRow.conflict_id == conflict.conflict_id
                )
            ).all()
        )
        existing_evidence = set(
            session.scalars(
                select(ConflictEvidenceRow.evidence_id).where(
                    ConflictEvidenceRow.conflict_id == conflict.conflict_id
                )
            ).all()
        )
        session.add_all(
            ConflictClaimRow(conflict_id=conflict.conflict_id, claim_id=claim_id)
            for claim_id in conflict.claim_ids
            if claim_id not in existing_claims
        )
        session.add_all(
            ConflictEvidenceRow(conflict_id=conflict.conflict_id, evidence_id=evidence_id)
            for evidence_id in conflict.evidence_ids
            if evidence_id not in existing_evidence
        )

    @staticmethod
    def _persist_families(session: Session, outcome: ValidationOutcome) -> None:
        validation_id = outcome.result.validation_id
        for family in outcome.lineage.families:
            digest = hashlib.sha256(f"{validation_id}:{family.family_id}".encode()).hexdigest()[:24]
            family_record_id = f"FR-{digest}"
            session.add(
                SourceFamilyRow(
                    family_record_id=family_record_id,
                    validation_id=validation_id,
                    run_id=outcome.result.run_id,
                    family_id=family.family_id,
                    lineage_version=outcome.lineage.version,
                    origin_type=family.origin_type,
                    independence_basis=list(family.independence_basis),
                    confidence=family.confidence,
                    resolution_method=family.resolution_method,
                )
            )
            session.flush()
            session.add_all(
                SourceFamilyMemberRow(
                    family_record_id=family_record_id,
                    source_id=source_id,
                )
                for source_id in family.member_source_ids
            )


@dataclass(frozen=True, slots=True)
class PersistValidationOperation:
    request: ValidationRequest
    outcome: ValidationOutcome

    def apply(self, session: Session, repository: InvestigationRepository) -> None:
        ValidationPersistence.persist_in_session(
            session,
            repository,
            request=self.request,
            outcome=self.outcome,
        )
