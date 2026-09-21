from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime

from pydantic import JsonValue

from marketpulse.investigation.domain.claims import ConflictSet
from marketpulse.investigation.domain.enums import (
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictStatus,
    ConflictType,
    QualityLevel,
    SemanticJudgmentStatus,
)
from marketpulse.investigation.validation.models import (
    ConflictDetectionResult,
    ConflictObservation,
    SemanticJudgment,
    SourceQualityAssessment,
    StrongContradictionAssessment,
)


class ConflictDetector:
    def detect(
        self,
        *,
        investigation_id: str,
        run_id: str,
        observations: tuple[ConflictObservation, ...],
        created_at: datetime,
    ) -> ConflictDetectionResult:
        by_claim: dict[str, list[ConflictObservation]] = defaultdict(list)
        for observation in observations:
            by_claim[observation.claim_id].append(observation)
        conflicts: list[ConflictSet] = []
        comparisons = 0
        for claim_id in sorted(by_claim):
            items = sorted(by_claim[claim_id], key=lambda item: item.evidence_id)
            for index, left in enumerate(items):
                for right in items[index + 1 :]:
                    comparisons += 1
                    conflict = self._compare(
                        investigation_id=investigation_id,
                        run_id=run_id,
                        claim_id=claim_id,
                        left=left,
                        right=right,
                        created_at=created_at,
                    )
                    if conflict is not None:
                        conflicts.append(conflict)
        return ConflictDetectionResult(
            conflicts=tuple(conflicts),
            compared_observations=comparisons,
        )

    def _compare(
        self,
        *,
        investigation_id: str,
        run_id: str,
        claim_id: str,
        left: ConflictObservation,
        right: ConflictObservation,
        created_at: datetime,
    ) -> ConflictSet | None:
        same_numeric = (
            left.numeric_value is not None
            and right.numeric_value is not None
            and left.numeric_value == right.numeric_value
            and left.unit == right.unit
        )
        if same_numeric and left.statement == right.statement:
            return None
        if (
            left.numeric_value is None
            and right.numeric_value is None
            and left.statement == right.statement
        ):
            return None

        conflict_type = (
            ConflictType.QUANTITATIVE
            if left.numeric_value is not None or right.numeric_value is not None
            else left.conflict_type
            if left.conflict_type == right.conflict_type
            else ConflictType.OTHER
        )
        resolution, explanations, basis = self._resolution(left, right)
        if resolution is ConflictResolutionStatus.NO_CONFLICT:
            return None
        status = (
            ConflictStatus.RESOLVED
            if resolution is not ConflictResolutionStatus.UNRESOLVED
            else ConflictStatus.REQUIRES_RESEARCH
        )
        severity = (
            ConflictSeverity.HIGH
            if conflict_type
            in {ConflictType.QUANTITATIVE, ConflictType.CAUSAL, ConflictType.ATTRIBUTION}
            else ConflictSeverity.MEDIUM
        )
        competing = (
            self._competing_value(left),
            self._competing_value(right),
        )
        conflict_id = self._conflict_id(run_id, claim_id, left.evidence_id, right.evidence_id)
        return ConflictSet(
            conflict_id=conflict_id,
            investigation_id=investigation_id,
            run_id=run_id,
            claim_ids=(claim_id,),
            evidence_ids=tuple(sorted((left.evidence_id, right.evidence_id))),
            conflict_type=conflict_type,
            severity=severity,
            status=status,
            competing_values=competing,
            possible_explanations=explanations,
            resolution_status=resolution,
            resolution_basis=basis,
            resolution_summary=basis,
            created_at=created_at,
            updated_at=created_at,
        )

    @staticmethod
    def _resolution(
        left: ConflictObservation,
        right: ConflictObservation,
    ) -> tuple[ConflictResolutionStatus, tuple[str, ...], str]:
        if left.unit and right.unit and left.unit.casefold() != right.unit.casefold():
            return (
                ConflictResolutionStatus.UNRESOLVED,
                (f"unit mismatch: {left.unit} versus {right.unit}",),
                "Different units cannot be treated as the same quantitative value "
                "without an explicit conversion and common scope",
            )
        if left.scope and right.scope and left.scope.casefold() != right.scope.casefold():
            return (
                ConflictResolutionStatus.RESOLVED_WITH_SCOPE,
                ("observations use different geographic or population scopes",),
                "Competing values are scoped to different populations or geographies",
            )
        if (
            left.definition
            and right.definition
            and left.definition.casefold() != right.definition.casefold()
        ):
            return (
                ConflictResolutionStatus.RESOLVED_WITH_DEFINITION,
                ("observations use different definitions",),
                "Competing values use different stated definitions",
            )
        temporal_evolution = (
            left.report_time is not None
            and right.report_time is not None
            and left.report_time != right.report_time
            and {left.report_stage, right.report_stage} <= {"PRELIMINARY", "INTERIM", "FINAL"}
            and "FINAL" in {left.report_stage, right.report_stage}
        )
        if temporal_evolution:
            return (
                ConflictResolutionStatus.RESOLVED_WITH_TIME,
                ("preliminary/interim figure was superseded by a later final figure",),
                "Metadata identifies temporal reporting evolution",
            )
        return (
            ConflictResolutionStatus.UNRESOLVED,
            ("methodology, scope, definition, or reporting time may differ",),
            "No metadata explains the competing statements or values",
        )

    @staticmethod
    def _competing_value(observation: ConflictObservation) -> JsonValue:
        return {
            "evidence_id": observation.evidence_id,
            "statement": observation.statement,
            "value": observation.numeric_value,
            "unit": observation.unit,
            "report_time": (
                observation.report_time.isoformat() if observation.report_time is not None else None
            ),
            "scope": observation.scope,
            "definition": observation.definition,
            "methodology": observation.methodology,
            "report_stage": observation.report_stage,
        }

    @staticmethod
    def _conflict_id(run_id: str, claim_id: str, left_id: str, right_id: str) -> str:
        payload = json.dumps(
            [run_id, claim_id, *sorted((left_id, right_id))],
            separators=(",", ":"),
        )
        return f"CF-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


class StrongContradictionGate:
    """Blocks sufficiency when a strong direct contradiction exists, regardless of vote count."""

    def assess(
        self,
        *,
        judgments: tuple[SemanticJudgment, ...],
        quality_by_evidence: dict[str, SourceQualityAssessment],
        observation_by_evidence: dict[str, ConflictObservation],
    ) -> StrongContradictionAssessment:
        triggered: list[str] = []
        basis: list[str] = []
        for judgment in sorted(judgments, key=lambda item: item.evidence_id):
            if judgment.judgment is not SemanticJudgmentStatus.CONTRADICTS:
                continue
            quality = quality_by_evidence.get(judgment.evidence_id)
            observation = observation_by_evidence.get(judgment.evidence_id)
            if quality is None or observation is None:
                continue
            direct = observation.directness >= 0.7
            specific = observation.specificity >= 0.7
            method = quality.component("methodology_transparency").level in {
                QualityLevel.STRONG,
                QualityLevel.ADEQUATE,
            }
            first_hand = quality.component("first_hand").level is QualityLevel.STRONG
            official_direct = (
                quality.component("official_direct_participant").level is QualityLevel.STRONG
            )
            temporal = quality.component("temporal_proximity").level is not QualityLevel.WEAK
            strong = (
                judgment.semantic_confidence >= 0.7
                and direct
                and specific
                and method
                and temporal
                and (first_hand or official_direct)
                and (quality.normalized_score or 0.0) >= 0.6
            )
            if strong:
                triggered.append(judgment.evidence_id)
                basis.append(
                    f"{judgment.evidence_id} is direct, specific, method-supported, "
                    "temporally usable strong counter-evidence"
                )
        if not basis:
            basis.append("no contradiction met the strong direct counter-evidence threshold")
        return StrongContradictionAssessment(
            triggered=bool(triggered),
            evidence_ids=tuple(triggered),
            basis=tuple(basis),
        )
