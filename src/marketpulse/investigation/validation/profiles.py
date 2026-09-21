from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from marketpulse.investigation.domain.claims import Claim, ConflictSet
from marketpulse.investigation.domain.enums import (
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictType,
    ImpactSubtype,
    ResearchGapType,
    SemanticJudgmentStatus,
    SourceType,
)
from marketpulse.investigation.domain.sources import Source
from marketpulse.investigation.validation.models import (
    IndependentEvidenceAssessment,
    ProfileSufficiency,
    SemanticJudgment,
    SourceQualityAssessment,
    StrongContradictionAssessment,
)


@dataclass(frozen=True, slots=True)
class ProfileContext:
    claim: Claim
    judgments: tuple[SemanticJudgment, ...]
    evidence_to_source: dict[str, str]
    source_by_id: dict[str, Source]
    independence: IndependentEvidenceAssessment
    quality_by_source: dict[str, SourceQualityAssessment]
    conflicts: tuple[ConflictSet, ...]
    strong_contradiction: StrongContradictionAssessment

    @property
    def entailing_evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            item.evidence_id
            for item in self.judgments
            if item.judgment is SemanticJudgmentStatus.ENTAILS
        )

    @property
    def supporting_evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            item.evidence_id
            for item in self.judgments
            if item.judgment
            in {SemanticJudgmentStatus.ENTAILS, SemanticJudgmentStatus.PARTIALLY_SUPPORTS}
        )

    @property
    def unresolved_conflicts(self) -> tuple[ConflictSet, ...]:
        return tuple(
            conflict
            for conflict in self.conflicts
            if conflict.resolution_status is ConflictResolutionStatus.UNRESOLVED
        )

    def source_for_evidence(self, evidence_id: str) -> Source | None:
        source_id = self.evidence_to_source.get(evidence_id)
        return self.source_by_id.get(source_id) if source_id is not None else None


class ValidationProfile(Protocol):
    claim_type: ClaimType
    version: str

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency: ...


class BaseProfile:
    claim_type: ClaimType
    version = "validation-profiles-v1"

    def _result(
        self,
        *,
        sufficient: bool,
        status: str,
        missing: list[str],
        gaps: list[ResearchGapType],
        basis: list[str],
        special: list[str] | None = None,
    ) -> ProfileSufficiency:
        if status not in {"VERIFIED", "PROBABLE", "UNVERIFIED"}:
            raise ValueError(status)
        return ProfileSufficiency(
            profile=self.claim_type,
            profile_version=self.version,
            sufficient=sufficient,
            recommended_status=status,  # type: ignore[arg-type]
            missing_requirements=tuple(missing),
            gap_codes=tuple(item.value for item in gaps),
            basis=tuple(basis),
            special_semantic_checks=tuple(special or ()),
        )

    @staticmethod
    def _supporting_quality_count(
        context: ProfileContext,
        *,
        minimum: float = 0.6,
    ) -> int:
        source_ids: set[str] = set()
        for evidence_id in context.supporting_evidence_ids:
            source_id = context.evidence_to_source.get(evidence_id)
            assessment = context.quality_by_source.get(source_id) if source_id else None
            if (
                source_id is not None
                and assessment is not None
                and (assessment.normalized_score or 0.0) >= minimum
            ):
                source_ids.add(source_id)
        return len(source_ids)

    @classmethod
    def _has_primary_entailment(cls, context: ProfileContext) -> bool:
        for evidence_id in context.entailing_evidence_ids:
            source = context.source_for_evidence(evidence_id)
            quality = context.quality_by_source.get(source.source_id) if source else None
            if (
                source is not None
                and quality is not None
                and (quality.normalized_score or 0.0) >= 0.6
                and (
                    source.is_first_hand
                    or source.source_type
                    in {
                        SourceType.OFFICIAL_REPORT,
                        SourceType.OFFICIAL_STATEMENT,
                        SourceType.PUBLIC_DATA,
                    }
                )
            ):
                return True
        return False


class StatementProfile(BaseProfile):
    claim_type = ClaimType.STATEMENT

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        primary = self._has_primary_entailment(context)
        sufficient = bool(context.entailing_evidence_ids) and primary
        missing: list[str] = []
        gaps: list[ResearchGapType] = []
        if not context.entailing_evidence_ids:
            missing.append("an exact ENTAILS judgment for the attributed statement")
            gaps.append(ResearchGapType.INSUFFICIENT_ENTAILMENT)
        if not primary:
            missing.append("authoritative original statement record")
            gaps.append(ResearchGapType.MISSING_PRIMARY_SOURCE)
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=[
                "STATEMENT verifies what the source stated, not the objective truth of its content"
            ],
            special=["attributed statement semantics retained"],
        )


class InstitutionalActionProfile(BaseProfile):
    claim_type = ClaimType.INSTITUTIONAL_ACTION

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        required = ("actor", "action", "scope")
        missing = [
            f"qualifier:{item}" for item in required if not context.claim.qualifiers.get(item)
        ]
        if not (context.claim.qualifiers.get("date") or context.claim.qualifiers.get("time")):
            missing.append("qualifier:date_or_time")
        if not self._has_primary_entailment(context):
            missing.append("direct institutional record with ENTAILS judgment")
        sufficient = not missing and not context.strong_contradiction.triggered
        gaps = [ResearchGapType.MISSING_PRIMARY_SOURCE] if missing else []
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=[
                "actor, action, time, scope, direct record, locator, and entailment are required"
            ],
        )


class EventFactProfile(BaseProfile):
    claim_type = ClaimType.EVENT_FACT

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        missing: list[str] = []
        gaps: list[ResearchGapType] = []
        if not self._has_primary_entailment(context):
            missing.append("strong first-hand Evidence")
            gaps.append(ResearchGapType.MISSING_PRIMARY_SOURCE)
        explicit_exception = bool(context.claim.qualifiers.get("authoritative_exception_basis"))
        if context.independence.independent_family_count < 2 and not explicit_exception:
            missing.append("independent corroborating family")
            gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
        if self._supporting_quality_count(context) < (1 if explicit_exception else 2):
            missing.append("adequate-quality corroborating Evidence")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        if context.unresolved_conflicts:
            missing.append("resolution of material conflicts")
            gaps.append(ResearchGapType.SOURCE_CONFLICT)
        sufficient = not missing and not context.strong_contradiction.triggered
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=["EVENT_FACT requires first-hand support and independent corroboration"],
            special=["official source alone is not sufficient"],
        )


class QuantitativeProfile(BaseProfile):
    claim_type = ClaimType.QUANTITATIVE

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        required = ("value", "unit", "time", "scope", "definition")
        missing = [
            f"qualifier:{item}" for item in required if context.claim.qualifiers.get(item) is None
        ]
        if not (
            context.claim.qualifiers.get("methodology")
            or context.claim.qualifiers.get("provenance")
        ):
            missing.append("methodology_or_provenance")
        gaps: list[ResearchGapType] = []
        required_families = (
            2 if context.claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL} else 1
        )
        if context.independence.independent_family_count < required_families:
            missing.append(f"{required_families} independent provenance families")
            gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
        if self._supporting_quality_count(context) < required_families:
            missing.append(f"{required_families} adequate-quality supporting Sources")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        unresolved_quantitative = any(
            conflict.conflict_type is ConflictType.QUANTITATIVE
            for conflict in context.unresolved_conflicts
        )
        if unresolved_quantitative:
            missing.append("resolution of quantitative conflict")
            gaps.append(ResearchGapType.UNRESOLVED_QUANTITATIVE_CONFLICT)
        sufficient = (
            not missing
            and bool(context.entailing_evidence_ids)
            and not context.strong_contradiction.triggered
        )
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=["value, unit, time, scope, definition, and provenance are evaluated separately"],
            special=["competing values are never averaged"],
        )


class CausalProfile(BaseProfile):
    claim_type = ClaimType.CAUSAL

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        required_true = (
            "temporal_ordering",
            "mechanism_support",
            "causal_attribution_evidence",
            "alternative_explanations_considered",
        )
        missing = [
            f"qualifier:{item}"
            for item in required_true
            if context.claim.qualifiers.get(item) is not True
        ]
        gaps: list[ResearchGapType] = []
        if context.claim.qualifiers.get("mechanism_support") is not True:
            gaps.append(ResearchGapType.MISSING_MECHANISM)
        if context.claim.qualifiers.get("causal_attribution_evidence") is not True:
            gaps.append(ResearchGapType.MISSING_CAUSAL_SUPPORT)
        if context.independence.independent_family_count < 2:
            missing.append("independent causal corroboration")
            gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
        if self._supporting_quality_count(context) < 2:
            missing.append("two adequate-quality causal Sources")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        sufficient = (
            not missing
            and bool(context.entailing_evidence_ids)
            and not context.strong_contradiction.triggered
            and not context.unresolved_conflicts
        )
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=["temporal order alone never establishes causation"],
            special=[
                "mechanism, attribution, alternatives, corroboration, and counter-evidence checked"
            ],
        )


class ImpactProfile(BaseProfile):
    claim_type = ClaimType.IMPACT

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        raw_subtype = context.claim.qualifiers.get("impact_subtype")
        try:
            subtype = ImpactSubtype(str(raw_subtype))
        except ValueError:
            subtype = None
        missing: list[str] = []
        gaps: list[ResearchGapType] = []
        if subtype is None:
            missing.append("valid impact_subtype")
        causal = subtype in {ImpactSubtype.CAUSAL_IMPACT, ImpactSubtype.LONG_TERM_IMPACT}
        if causal:
            for key in ("temporal_ordering", "mechanism_support", "causal_attribution_evidence"):
                if context.claim.qualifiers.get(key) is not True:
                    missing.append(f"qualifier:{key}")
            if context.claim.qualifiers.get("mechanism_support") is not True:
                gaps.append(ResearchGapType.MISSING_MECHANISM)
            if context.independence.independent_family_count < 2:
                missing.append("independent causal impact corroboration")
                gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
            if self._supporting_quality_count(context) < 2:
                missing.append("two adequate-quality causal impact Sources")
                gaps.append(ResearchGapType.EVIDENCE_GAP)
        elif self._supporting_quality_count(context) < 1:
            missing.append("adequate-quality direct impact report")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        sufficient = (
            not missing
            and bool(context.entailing_evidence_ids)
            and not context.strong_contradiction.triggered
        )
        status = (
            "VERIFIED" if sufficient and not causal else "PROBABLE" if sufficient else "UNVERIFIED"
        )
        return self._result(
            sufficient=sufficient,
            status=status,
            missing=missing,
            gaps=gaps,
            basis=[f"IMPACT semantic role is {subtype.value if subtype else 'UNKNOWN'}"],
            special=["reported symptom support does not imply causal impact"],
        )


class AttributionProfile(BaseProfile):
    claim_type = ClaimType.ATTRIBUTION

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        kinds = {
            "DOCUMENTED_ACTION",
            "INVESTIGATIVE_ATTRIBUTION",
            "REGULATORY_FINDING",
            "LEGAL_RESPONSIBILITY",
            "ANALYTICAL_ATTRIBUTION",
        }
        missing: list[str] = []
        gaps: list[ResearchGapType] = []
        if context.claim.qualifiers.get("attribution_kind") not in kinds:
            missing.append("recognized attribution_kind")
        if context.claim.qualifiers.get("interested_party_only") is not False:
            missing.append("support beyond interested-party assertion")
            gaps.append(ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED)
        if context.independence.independent_family_count < 2:
            missing.append("independent attribution support")
            gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
        if self._supporting_quality_count(context) < 2:
            missing.append("two adequate-quality attribution Sources")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        if context.claim.qualifiers.get("direct_finding") is not True:
            missing.append("direct investigative/regulatory/legal finding")
            gaps.append(ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED)
        sufficient = (
            not missing
            and bool(context.entailing_evidence_ids)
            and not context.strong_contradiction.triggered
        )
        return self._result(
            sufficient=sufficient,
            status="VERIFIED" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=["interested-party statements cannot independently establish responsibility"],
        )


class AnalyticInferenceProfile(BaseProfile):
    claim_type = ClaimType.ANALYTIC_INFERENCE

    def evaluate(self, context: ProfileContext) -> ProfileSufficiency:
        missing: list[str] = []
        gaps: list[ResearchGapType] = []
        if context.independence.independent_family_count < 2:
            missing.append("multi-family support")
            gaps.append(ResearchGapType.INSUFFICIENT_INDEPENDENCE)
        if not context.claim.qualifiers.get("reasoning_basis"):
            missing.append("explicit reasoning_basis")
        if not context.claim.qualifiers.get("uncertainty"):
            missing.append("explicit uncertainty")
        if len(context.supporting_evidence_ids) < 2:
            missing.append("multiple supporting Evidence items")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        if self._supporting_quality_count(context) < 2:
            missing.append("two adequate-quality supporting Sources")
            gaps.append(ResearchGapType.EVIDENCE_GAP)
        sufficient = not missing and not context.strong_contradiction.triggered
        return self._result(
            sufficient=sufficient,
            status="PROBABLE" if sufficient else "UNVERIFIED",
            missing=missing,
            gaps=gaps,
            basis=["analytical inference remains explicitly inferential and is capped at PROBABLE"],
            special=["cannot silently upgrade to EVENT_FACT"],
        )


PROFILES: dict[ClaimType, ValidationProfile] = {
    ClaimType.STATEMENT: StatementProfile(),
    ClaimType.INSTITUTIONAL_ACTION: InstitutionalActionProfile(),
    ClaimType.EVENT_FACT: EventFactProfile(),
    ClaimType.QUANTITATIVE: QuantitativeProfile(),
    ClaimType.CAUSAL: CausalProfile(),
    ClaimType.IMPACT: ImpactProfile(),
    ClaimType.ATTRIBUTION: AttributionProfile(),
    ClaimType.ANALYTIC_INFERENCE: AnalyticInferenceProfile(),
}
