from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime

from marketpulse.investigation.domain.claims import (
    ConflictSet,
    ResearchGap,
    ValidationResult,
)
from marketpulse.investigation.domain.enums import (
    ConflictResolutionStatus,
    ConflictSeverity,
    EntailmentStatus,
    GapSeverity,
    GapStatus,
    ImpactSubtype,
    ResearchGapType,
    SemanticJudgmentStatus,
    SourceType,
    ValidationStatus,
)
from marketpulse.investigation.domain.sources import Evidence, Source, SourceSnapshot
from marketpulse.investigation.validation.conflicts import (
    ConflictDetector,
    StrongContradictionGate,
)
from marketpulse.investigation.validation.independence import SourceIndependencePolicy
from marketpulse.investigation.validation.integrity import EvidenceIntegrityValidator
from marketpulse.investigation.validation.lineage import SourceLineageResolver
from marketpulse.investigation.validation.models import (
    EvidenceIntegrityResult,
    LineageResolution,
    SemanticJudgment,
    SourceQualityAssessment,
    ValidationBasis,
    ValidationOutcome,
    ValidationRequest,
)
from marketpulse.investigation.validation.profiles import PROFILES, ProfileContext
from marketpulse.investigation.validation.quality import SourceQualityAssessor

PIPELINE_STAGES = (
    "1:EVIDENCE_EXISTENCE",
    "2:SNAPSHOT_ARTIFACT_INTEGRITY",
    "3:LOCATOR_VALIDATION",
    "4:SEMANTIC_ENTAILMENT",
    "5:LINEAGE_PROVENANCE",
    "6:STRONG_CONTRADICTION_GATE",
    "7:INDEPENDENCE",
    "8:SOURCE_QUALITY",
    "9:CLAIM_TYPE_SUFFICIENCY",
    "10:CONFLICT_STATE",
    "11:VALIDATION_STATUS",
    "12:CONFIDENCE",
    "13:VALIDATION_BASIS",
    "14:CONFIDENCE_BASIS",
    "15:RESEARCH_GAP_DERIVATION",
)


class ValidationPolicy:
    VERSION = "validation-policy-v1"

    def __init__(
        self,
        *,
        integrity: EvidenceIntegrityValidator,
        lineage: SourceLineageResolver | None = None,
        independence: SourceIndependencePolicy | None = None,
        quality: SourceQualityAssessor | None = None,
        conflicts: ConflictDetector | None = None,
        contradiction_gate: StrongContradictionGate | None = None,
    ) -> None:
        self._integrity = integrity
        self._lineage = lineage or SourceLineageResolver()
        self._independence = independence or SourceIndependencePolicy()
        self._quality = quality or SourceQualityAssessor()
        self._conflicts = conflicts or ConflictDetector()
        self._contradiction_gate = contradiction_gate or StrongContradictionGate()

    def validate(self, request: ValidationRequest) -> ValidationOutcome:
        self._validate_request_relations(request)
        evidence_by_id = {item.evidence_id: item for item in request.evidence}
        snapshot_by_id = {item.snapshot_id: item for item in request.snapshots}
        artifact_by_id = {item.artifact_id: item for item in request.artifacts}
        source_by_id = {item.source_id: item for item in request.sources}
        referenced_ids = tuple(sorted({item.evidence_id for item in request.relations}))

        integrity_results = tuple(
            self._integrity.validate_reference(
                evidence_id=evidence_id,
                evidence_by_id=evidence_by_id,
                snapshot_by_id=snapshot_by_id,
                artifact_by_id=artifact_by_id,
            )
            for evidence_id in referenced_ids
        )
        valid_ids = frozenset(item.evidence_id for item in integrity_results if item.valid)
        judgments = self._usable_judgments(request, valid_ids)
        support_ids = frozenset(
            item.evidence_id
            for item in judgments
            if item.judgment
            in {SemanticJudgmentStatus.ENTAILS, SemanticJudgmentStatus.PARTIALLY_SUPPORTS}
        )

        lineage = self._lineage.resolve(
            sources=request.sources,
            snapshots=request.snapshots,
            explicit_attributions=request.explicit_attributions,
        )
        evidence_to_source = self._evidence_to_source(
            evidence_by_id,
            snapshot_by_id,
            source_by_id,
        )
        quality_by_source = self._assess_quality(
            request=request,
            lineage=lineage,
            source_by_id=source_by_id,
            snapshot_by_id=snapshot_by_id,
            evidence_to_source=evidence_to_source,
            valid_ids=valid_ids,
        )
        quality_by_evidence = {
            evidence_id: quality_by_source[source_id]
            for evidence_id, source_id in evidence_to_source.items()
            if evidence_id in valid_ids and source_id in quality_by_source
        }
        observation_by_evidence = {
            item.evidence_id: item
            for item in request.conflict_observations
            if item.evidence_id in valid_ids
        }
        strong = self._contradiction_gate.assess(
            judgments=judgments,
            quality_by_evidence=quality_by_evidence,
            observation_by_evidence=observation_by_evidence,
        )
        independence = self._independence.assess(
            evidence=request.evidence,
            eligible_evidence_ids=support_ids,
            snapshots=request.snapshots,
            sources=request.sources,
            lineage=lineage,
        )

        profile = PROFILES[request.claim.claim_type]
        profile_result = profile.evaluate(
            ProfileContext(
                claim=request.claim,
                judgments=judgments,
                evidence_to_source=evidence_to_source,
                source_by_id=source_by_id,
                independence=independence,
                quality_by_source=quality_by_source,
                conflicts=request.existing_conflicts,
                strong_contradiction=strong,
            )
        )
        detected = self._conflicts.detect(
            investigation_id=request.claim.investigation_id,
            run_id=request.claim.run_id,
            observations=tuple(observation_by_evidence.values()),
            created_at=request.created_at,
        )
        conflict_updates = self._merge_conflicts(request.existing_conflicts, detected.conflicts)
        status = self._status(
            profile_status=profile_result.recommended_status,
            profile_sufficient=profile_result.sufficient,
            strong=strong.triggered,
            conflicts=conflict_updates,
        )
        confidence, confidence_basis = self._confidence(
            status=status,
            judgments=judgments,
            independence_count=independence.independent_family_count,
            strong=strong.triggered,
            conflicts=conflict_updates,
            profile_sufficient=profile_result.sufficient,
        )
        basis = self._basis(
            request=request,
            integrity_results=integrity_results,
            judgments=judgments,
            independence_count=independence.independent_family_count,
            primary_count=independence.primary_family_count,
            strong=strong.triggered,
            conflicts=conflict_updates,
            quality_by_source=quality_by_source,
            profile_sufficient=profile_result.sufficient,
            special_checks=profile_result.special_semantic_checks,
        )
        input_fingerprint = self._input_fingerprint(request)
        evidence_set_hash = self._evidence_set_hash(request.evidence, referenced_ids)
        result = ValidationResult(
            validation_id=request.validation_id,
            claim_id=request.claim.claim_id,
            run_id=request.claim.run_id,
            claim_type=request.claim.claim_type,
            profile_version=profile_result.profile_version,
            policy_version=self.VERSION,
            input_fingerprint=input_fingerprint,
            evidence_set_hash=evidence_set_hash,
            lineage_version=lineage.version,
            conflict_set_refs=tuple(item.conflict_id for item in conflict_updates),
            citation_valid=bool(integrity_results)
            and all(item.valid for item in integrity_results),
            entailment_result=self._entailment_summary(judgments),
            independent_source_count=independence.independent_family_count,
            strong_contradiction=strong.triggered,
            source_quality_summary={
                source_id: assessment.normalized_score
                for source_id, assessment in sorted(quality_by_source.items())
            },
            sufficiency_result="SUFFICIENT" if profile_result.sufficient else "INSUFFICIENT",
            status=status,
            confidence=confidence,
            validation_basis="; ".join(profile_result.basis + strong.basis),
            validation_basis_payload=basis.model_dump(mode="json"),
            confidence_basis=confidence_basis,
            created_at=request.created_at,
        )
        gaps = self._derive_gaps(
            request=request,
            integrity_results=integrity_results,
            judgments=judgments,
            profile_gap_codes=profile_result.gap_codes,
            profile_missing=profile_result.missing_requirements,
            conflicts=conflict_updates,
            validation_id=request.validation_id,
        )
        semantic_hash = self.semantic_content_hash(result, conflict_updates, gaps)
        return ValidationOutcome(
            result=result,
            integrity_results=integrity_results,
            lineage=lineage,
            independence=independence,
            quality_assessments=tuple(
                quality_by_source[source_id] for source_id in sorted(quality_by_source)
            ),
            conflict_updates=conflict_updates,
            strong_contradiction=strong,
            research_gaps=gaps,
            pipeline_stages=PIPELINE_STAGES,
            semantic_content_hash=semantic_hash,
        )

    @staticmethod
    def semantic_content_hash(
        result: ValidationResult,
        conflicts: tuple[ConflictSet, ...],
        gaps: tuple[ResearchGap, ...],
    ) -> str:
        result_payload = result.model_dump(
            mode="json",
            exclude={"validation_id", "created_at"},
        )
        conflict_payload = [
            item.model_dump(
                mode="json",
                exclude={"conflict_id", "created_at", "updated_at"},
            )
            for item in conflicts
        ]
        gap_payload = [
            item.model_dump(
                mode="json",
                exclude={"gap_id", "created_at", "resolved_at"},
            )
            for item in gaps
        ]
        return _canonical_hash(
            {
                "result": result_payload,
                "conflicts": conflict_payload,
                "gaps": gap_payload,
            }
        )

    @staticmethod
    def _validate_request_relations(request: ValidationRequest) -> None:
        for relation in request.relations:
            if relation.claim_id != request.claim.claim_id:
                raise ValueError("ClaimEvidenceRelation belongs to another Claim")
        for judgment in request.semantic_judgments:
            if judgment.claim_id != request.claim.claim_id:
                raise ValueError("SemanticJudgment belongs to another Claim")
            if judgment.run_id != request.claim.run_id:
                raise ValueError("SemanticJudgment belongs to another Run")

    @staticmethod
    def _usable_judgments(
        request: ValidationRequest,
        valid_ids: frozenset[str],
    ) -> tuple[SemanticJudgment, ...]:
        referenced = {item.evidence_id for item in request.relations}
        by_evidence: dict[str, SemanticJudgment] = {}
        for judgment in request.semantic_judgments:
            if judgment.evidence_id in valid_ids and judgment.evidence_id in referenced:
                if judgment.evidence_id in by_evidence:
                    raise ValueError("multiple semantic judgments for one Claim/Evidence pair")
                by_evidence[judgment.evidence_id] = judgment
        return tuple(by_evidence[item] for item in sorted(by_evidence))

    @staticmethod
    def _evidence_to_source(
        evidence_by_id: Mapping[str, Evidence],
        snapshot_by_id: Mapping[str, SourceSnapshot],
        source_by_id: Mapping[str, Source],
    ) -> dict[str, str]:
        output: dict[str, str] = {}
        for evidence_id, evidence in evidence_by_id.items():
            snapshot = snapshot_by_id.get(evidence.snapshot_id)
            if snapshot is not None and snapshot.source_id in source_by_id:
                output[evidence_id] = snapshot.source_id
        return output

    def _assess_quality(
        self,
        *,
        request: ValidationRequest,
        lineage: LineageResolution,
        source_by_id: dict[str, Source],
        snapshot_by_id: dict[str, SourceSnapshot],
        evidence_to_source: dict[str, str],
        valid_ids: frozenset[str],
    ) -> dict[str, SourceQualityAssessment]:
        family_by_id = {item.family_id: item for item in lineage.families}
        snapshots_by_source: dict[str, list[SourceSnapshot]] = defaultdict(list)
        for snapshot in snapshot_by_id.values():
            snapshots_by_source[snapshot.source_id].append(snapshot)
        reference_by_source: dict[str, datetime] = {}
        for evidence in request.evidence:
            source_id = evidence_to_source.get(evidence.evidence_id)
            if evidence.evidence_id in valid_ids and source_id and evidence.event_time:
                reference_by_source.setdefault(source_id, evidence.event_time)
        output: dict[str, SourceQualityAssessment] = {}
        for source_id in sorted(set(evidence_to_source.values())):
            family_id = lineage.source_to_family.get(source_id)
            snapshots = snapshots_by_source.get(source_id)
            if family_id is None or not snapshots:
                continue
            snapshot = max(snapshots, key=lambda item: item.retrieved_at)
            reference = reference_by_source.get(source_id)
            output[source_id] = self._quality.assess(
                source=source_by_id[source_id],
                snapshot=snapshot,
                family=family_by_id[family_id],
                reference_time=reference,
            )
        return output

    @staticmethod
    def _merge_conflicts(
        existing: tuple[ConflictSet, ...],
        detected: tuple[ConflictSet, ...],
    ) -> tuple[ConflictSet, ...]:
        by_id = {item.conflict_id: item for item in (*existing, *detected)}
        return tuple(by_id[item] for item in sorted(by_id))

    @staticmethod
    def _status(
        *,
        profile_status: str,
        profile_sufficient: bool,
        strong: bool,
        conflicts: tuple[ConflictSet, ...],
    ) -> ValidationStatus:
        unresolved = any(
            item.resolution_status is ConflictResolutionStatus.UNRESOLVED
            and item.severity in {ConflictSeverity.HIGH, ConflictSeverity.BLOCKING}
            for item in conflicts
        )
        if strong or unresolved:
            return ValidationStatus.DISPUTED
        if not profile_sufficient:
            return ValidationStatus.UNVERIFIED
        if profile_status == "VERIFIED":
            return ValidationStatus.VERIFIED
        if profile_status == "PROBABLE":
            return ValidationStatus.PROBABLE
        return ValidationStatus.UNVERIFIED

    @staticmethod
    def _confidence(
        *,
        status: ValidationStatus,
        judgments: tuple[SemanticJudgment, ...],
        independence_count: int,
        strong: bool,
        conflicts: tuple[ConflictSet, ...],
        profile_sufficient: bool,
    ) -> tuple[float, str]:
        semantic = (
            sum(item.semantic_confidence for item in judgments) / len(judgments)
            if judgments
            else 0.0
        )
        if status is ValidationStatus.DISPUTED:
            confidence = 0.9 if strong or conflicts else 0.8
        elif status is ValidationStatus.VERIFIED:
            confidence = 0.85
        elif status is ValidationStatus.PROBABLE:
            confidence = 0.7
        else:
            confidence = 0.35 if judgments else 0.2
        unresolved_count = sum(
            item.resolution_status is ConflictResolutionStatus.UNRESOLVED for item in conflicts
        )
        basis = (
            f"policy-calibrated indicator: status={status.value}; semantic certainty band="
            f"{'high' if semantic >= 0.8 else 'medium' if semantic >= 0.5 else 'low'}; "
            f"independent families={independence_count}; profile sufficient={profile_sufficient}; "
            f"strong contradiction={strong}; unresolved conflicts={unresolved_count}"
        )
        return confidence, basis

    @staticmethod
    def _basis(
        *,
        request: ValidationRequest,
        integrity_results: tuple[EvidenceIntegrityResult, ...],
        judgments: tuple[SemanticJudgment, ...],
        independence_count: int,
        primary_count: int,
        strong: bool,
        conflicts: tuple[ConflictSet, ...],
        quality_by_source: dict[str, SourceQualityAssessment],
        profile_sufficient: bool,
        special_checks: tuple[str, ...],
    ) -> ValidationBasis:
        raw_subtype = request.claim.qualifiers.get("impact_subtype")
        try:
            impact_subtype = ImpactSubtype(str(raw_subtype)) if raw_subtype else None
        except ValueError:
            impact_subtype = None
        return ValidationBasis(
            profile=request.claim.claim_type,
            profile_sufficient=profile_sufficient,
            integrity_valid_evidence_ids=tuple(
                item.evidence_id for item in integrity_results if item.valid
            ),
            integrity_failures={
                item.evidence_id: tuple(failure.code.value for failure in item.failures)
                for item in integrity_results
                if item.failures
            },
            semantic_judgments={item.evidence_id: item.judgment.value for item in judgments},
            independent_family_count=independence_count,
            primary_family_count=primary_count,
            strong_contradiction=strong,
            unresolved_conflict_ids=tuple(
                item.conflict_id
                for item in conflicts
                if item.resolution_status is ConflictResolutionStatus.UNRESOLVED
            ),
            quality_scores={
                source_id: item.normalized_score
                for source_id, item in sorted(quality_by_source.items())
            },
            impact_subtype=impact_subtype,
            special_checks=special_checks,
        )

    def _derive_gaps(
        self,
        *,
        request: ValidationRequest,
        integrity_results: tuple[EvidenceIntegrityResult, ...],
        judgments: tuple[SemanticJudgment, ...],
        profile_gap_codes: tuple[str, ...],
        profile_missing: tuple[str, ...],
        conflicts: tuple[ConflictSet, ...],
        validation_id: str,
    ) -> tuple[ResearchGap, ...]:
        entries: list[tuple[ResearchGapType, str, str, str]] = []
        for result in integrity_results:
            if result.valid:
                continue
            codes = ", ".join(item.code.value for item in result.failures)
            entries.append(
                (
                    ResearchGapType.EVIDENCE_GAP,
                    f"Evidence {result.evidence_id} failed integrity: {codes}",
                    "valid immutable evidence chain",
                    "repair or replace the Evidence with a valid Snapshot, Artifact, "
                    "Blob, and locator",
                )
            )
        judged_ids = {item.evidence_id for item in judgments}
        valid_ids = {item.evidence_id for item in integrity_results if item.valid}
        if valid_ids - judged_ids:
            entries.append(
                (
                    ResearchGapType.INSUFFICIENT_ENTAILMENT,
                    "valid Evidence lacks a semantic entailment judgment",
                    "semantic judgment for every usable Evidence item",
                    "obtain or replay a schema-compatible semantic judgment",
                )
            )
        for code in profile_gap_codes:
            gap_type = ResearchGapType(code)
            missing = self._gap_requirement(gap_type, profile_missing)
            entries.append(
                (
                    gap_type,
                    f"Profile requirement is not met: {missing}",
                    missing,
                    self._suggested_action(gap_type),
                )
            )
        for conflict in conflicts:
            if conflict.resolution_status is not ConflictResolutionStatus.UNRESOLVED:
                continue
            gap_type = (
                ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT
                if conflict.conflict_type.value == "QUANTITATIVE"
                else ResearchGapType.SOURCE_CONFLICT
            )
            entries.append(
                (
                    gap_type,
                    f"Conflict {conflict.conflict_id} remains unresolved",
                    "scope/time/definition/methodology evidence that resolves the conflict",
                    "collect direct metadata or a stronger source that explains the conflict",
                )
            )

        unique: dict[tuple[ResearchGapType, str], tuple[str, str]] = {}
        for gap_type, reason, missing, action in entries:
            unique[(gap_type, missing)] = (reason, action)
        gaps: list[ResearchGap] = []
        for index, ((gap_type, missing), (reason, action)) in enumerate(
            sorted(unique.items(), key=lambda item: (item[0][0].value, item[0][1]))
        ):
            severity = (
                GapSeverity.BLOCKING
                if request.claim.is_critical
                or gap_type
                in {
                    ResearchGapType.SOURCE_CONFLICT,
                    ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT,
                    ResearchGapType.MISSING_CAUSAL_SUPPORT,
                }
                else GapSeverity.HIGH
            )
            gaps.append(
                ResearchGap(
                    gap_id=f"GAP-{hashlib.sha256(f'{validation_id}:{index}:{gap_type.value}'.encode()).hexdigest()[:24]}",
                    investigation_id=request.claim.investigation_id,
                    run_id=request.claim.run_id,
                    gap_type=gap_type,
                    target_question_id=request.target_question_id,
                    target_claim_id=request.claim.claim_id,
                    reason=reason,
                    preferred_source_type=self._preferred_source_type(gap_type),
                    missing_requirement=missing,
                    suggested_action=action,
                    severity=severity,
                    status=GapStatus.OPEN,
                    suggested_actions=(action,),
                    created_at=request.created_at,
                )
            )
        return tuple(gaps)

    @staticmethod
    def _gap_requirement(
        gap_type: ResearchGapType,
        profile_missing: tuple[str, ...],
    ) -> str:
        keywords = {
            ResearchGapType.MISSING_PRIMARY_SOURCE: ("primary", "original", "direct"),
            ResearchGapType.INSUFFICIENT_INDEPENDENCE: ("independent", "family"),
            ResearchGapType.INSUFFICIENT_ENTAILMENT: ("entail", "semantic"),
            ResearchGapType.MISSING_CAUSAL_SUPPORT: ("causal_attribution", "causal support"),
            ResearchGapType.MISSING_MECHANISM: ("mechanism",),
            ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT: ("quantitative conflict",),
            ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED: ("attribution", "finding"),
            ResearchGapType.EVIDENCE_GAP: ("quality", "Evidence", "evidence"),
        }
        for missing in profile_missing:
            if any(
                keyword.casefold() in missing.casefold() for keyword in keywords.get(gap_type, ())
            ):
                return missing
        return gap_type.value

    @staticmethod
    def _preferred_source_type(gap_type: ResearchGapType) -> SourceType | None:
        if gap_type in {
            ResearchGapType.MISSING_PRIMARY_SOURCE,
            ResearchGapType.MISSING_CAUSAL_SUPPORT,
            ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED,
        }:
            return SourceType.OFFICIAL_REPORT
        if gap_type is ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT:
            return SourceType.PUBLIC_DATA
        return None

    @staticmethod
    def _suggested_action(gap_type: ResearchGapType) -> str:
        actions = {
            ResearchGapType.MISSING_PRIMARY_SOURCE: "locate the original direct record",
            ResearchGapType.INSUFFICIENT_INDEPENDENCE: (
                "collect a genuinely independent provenance family"
            ),
            ResearchGapType.INSUFFICIENT_ENTAILMENT: (
                "obtain an exact semantic judgment for valid Evidence"
            ),
            ResearchGapType.MISSING_CAUSAL_SUPPORT: "collect direct causal attribution evidence",
            ResearchGapType.MISSING_MECHANISM: "collect evidence for the proposed mechanism",
            ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT: (
                "resolve value, unit, time, scope, definition, and methodology"
            ),
            ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED: (
                "obtain an independent investigative, regulatory, or legal finding"
            ),
        }
        return actions.get(
            gap_type, "collect evidence that satisfies the missing profile requirement"
        )

    @staticmethod
    def _entailment_summary(judgments: tuple[SemanticJudgment, ...]) -> EntailmentStatus:
        values = {item.judgment for item in judgments}
        if SemanticJudgmentStatus.CONTRADICTS in values:
            return EntailmentStatus.CONTRADICTED
        if values and values <= {SemanticJudgmentStatus.ENTAILS}:
            return EntailmentStatus.ENTAILED
        if values & {
            SemanticJudgmentStatus.PARTIALLY_SUPPORTS,
            SemanticJudgmentStatus.UNCERTAIN,
        }:
            return EntailmentStatus.UNCERTAIN
        return EntailmentStatus.NOT_ENTAILED

    def _input_fingerprint(self, request: ValidationRequest) -> str:
        return _canonical_hash(
            {
                "policy_version": self.VERSION,
                "claim": request.claim.model_dump(
                    mode="json",
                    exclude={
                        "validation_status",
                        "confidence",
                        "confidence_basis",
                        "latest_validation_id",
                        "created_at",
                        "updated_at",
                    },
                ),
                "relations": [item.model_dump(mode="json") for item in request.relations],
                "evidence": [item.model_dump(mode="json") for item in request.evidence],
                "snapshots": [item.model_dump(mode="json") for item in request.snapshots],
                "artifacts": [item.model_dump(mode="json") for item in request.artifacts],
                "sources": [item.model_dump(mode="json") for item in request.sources],
                "semantic_judgments": [
                    item.model_dump(mode="json", exclude={"judgment_id", "created_at"})
                    for item in request.semantic_judgments
                ],
                "attributions": [
                    item.model_dump(mode="json") for item in request.explicit_attributions
                ],
                "conflict_observations": [
                    item.model_dump(mode="json") for item in request.conflict_observations
                ],
                "existing_conflicts": [
                    item.model_dump(mode="json", exclude={"created_at", "updated_at"})
                    for item in request.existing_conflicts
                ],
            }
        )

    @staticmethod
    def _evidence_set_hash(
        evidence: tuple[Evidence, ...],
        referenced_ids: tuple[str, ...],
    ) -> str:
        referenced = set(referenced_ids)
        return _canonical_hash(
            [
                {"evidence_id": item.evidence_id, "content_hash": item.content_hash}
                for item in sorted(evidence, key=lambda value: value.evidence_id)
                if item.evidence_id in referenced
            ]
        )


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
