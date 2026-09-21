from __future__ import annotations

from datetime import datetime

from marketpulse.investigation.domain.enums import QualityLevel, SourceType
from marketpulse.investigation.domain.sources import Source, SourceSnapshot
from marketpulse.investigation.validation.models import (
    QualityComponent,
    SourceFamily,
    SourceQualityAssessment,
)

_LEVEL_SCORE = {
    QualityLevel.STRONG: 1.0,
    QualityLevel.ADEQUATE: 0.65,
    QualityLevel.WEAK: 0.25,
    QualityLevel.UNKNOWN: 0.5,
}


class SourceQualityAssessor:
    """Assesses evidence characteristics without publisher-brand priors."""

    def assess(
        self,
        *,
        source: Source,
        snapshot: SourceSnapshot,
        family: SourceFamily,
        reference_time: datetime | None = None,
        consistent_with_stronger_evidence: bool | None = None,
    ) -> SourceQualityAssessment:
        provenance = snapshot.provenance
        components = (
            self._component(
                "first_hand",
                QualityLevel.STRONG if source.is_first_hand else QualityLevel.WEAK,
                "Source declares first-hand status"
                if source.is_first_hand
                else "Source is not identified as first-hand",
            ),
            self._component(
                "official_direct_participant",
                QualityLevel.STRONG if source.is_official else QualityLevel.UNKNOWN,
                "Source is an official/direct participant record; this does not prove world truth"
                if source.is_official
                else "No direct institutional status is established",
            ),
            self._component(
                "primary_source",
                QualityLevel.STRONG
                if source.is_first_hand
                or source.source_type
                in {
                    SourceType.OFFICIAL_REPORT,
                    SourceType.OFFICIAL_STATEMENT,
                    SourceType.PUBLIC_DATA,
                }
                else QualityLevel.WEAK,
                "Source metadata identifies a primary record"
                if source.is_first_hand
                or source.source_type
                in {
                    SourceType.OFFICIAL_REPORT,
                    SourceType.OFFICIAL_STATEMENT,
                    SourceType.PUBLIC_DATA,
                }
                else "Source appears secondary",
            ),
            self._metadata_component(
                "data_provenance",
                provenance.get("data_provenance"),
                "data provenance",
            ),
            self._metadata_component(
                "methodology_transparency",
                provenance.get("methodology"),
                "methodology",
            ),
            self._component(
                "named_author_source",
                QualityLevel.STRONG
                if source.author
                else QualityLevel.ADEQUATE
                if source.organization or source.publisher
                else QualityLevel.WEAK,
                "Named author/source metadata is present"
                if source.author or source.organization or source.publisher
                else "No named author, organization, or publisher",
            ),
            self._temporal_component(source, snapshot, reference_time),
            self._component(
                "retransmission_depth",
                QualityLevel.WEAK
                if source.origin_source_id or source.syndication_cluster_id
                else QualityLevel.STRONG
                if source.is_first_hand
                else QualityLevel.UNKNOWN,
                "Source is a retransmission or syndicated member"
                if source.origin_source_id or source.syndication_cluster_id
                else "No retransmission link is recorded",
            ),
            self._inverse_metadata_component(
                "speculation_level",
                provenance.get("speculation_level"),
                "speculation",
            ),
            self._component(
                "source_independence",
                QualityLevel.STRONG
                if len(family.member_source_ids) == 1
                else QualityLevel.ADEQUATE,
                "Source forms its own provenance family"
                if len(family.member_source_ids) == 1
                else "Source shares a provenance family with retransmissions or attributions",
            ),
            self._component(
                "explicit_uncertainty",
                QualityLevel.STRONG
                if provenance.get("explicit_uncertainty") is True
                else QualityLevel.UNKNOWN,
                "Source states uncertainty explicitly"
                if provenance.get("explicit_uncertainty") is True
                else "Explicit uncertainty metadata is absent",
            ),
            self._consistency_component(consistent_with_stronger_evidence),
        )
        normalized = round(
            sum(item.normalized_value or 0.0 for item in components) / len(components),
            2,
        )
        return SourceQualityAssessment(
            source_id=source.source_id,
            family_id=family.family_id,
            components=components,
            basis=tuple(item.basis for item in components),
            normalized_score=normalized,
        )

    @staticmethod
    def _component(name: str, level: QualityLevel, basis: str) -> QualityComponent:
        return QualityComponent(
            name=name,
            level=level,
            basis=basis,
            normalized_value=_LEVEL_SCORE[level],
        )

    def _metadata_component(
        self,
        name: str,
        value: object,
        label: str,
    ) -> QualityComponent:
        if isinstance(value, str) and value.strip():
            return self._component(name, QualityLevel.STRONG, f"Explicit {label} is recorded")
        if value is True:
            return self._component(name, QualityLevel.STRONG, f"Explicit {label} is recorded")
        return self._component(name, QualityLevel.UNKNOWN, f"No explicit {label} metadata")

    def _inverse_metadata_component(
        self,
        name: str,
        value: object,
        label: str,
    ) -> QualityComponent:
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric <= 0.25:
                return self._component(name, QualityLevel.STRONG, f"Low {label} is recorded")
            if numeric >= 0.75:
                return self._component(name, QualityLevel.WEAK, f"High {label} is recorded")
            return self._component(name, QualityLevel.ADEQUATE, f"Moderate {label} is recorded")
        return self._component(name, QualityLevel.UNKNOWN, f"No explicit {label} metadata")

    def _temporal_component(
        self,
        source: Source,
        snapshot: SourceSnapshot,
        reference_time: datetime | None,
    ) -> QualityComponent:
        if source.published_at is None or reference_time is None:
            return self._component(
                "temporal_proximity",
                QualityLevel.UNKNOWN,
                "Event/reference time or publication time is unavailable",
            )
        distance = abs((source.published_at - reference_time).total_seconds())
        if distance <= 7 * 86_400:
            return self._component(
                "temporal_proximity",
                QualityLevel.STRONG,
                "Publication is within seven days of the reference time",
            )
        if source.published_at <= snapshot.retrieved_at:
            return self._component(
                "temporal_proximity",
                QualityLevel.ADEQUATE,
                "Publication predates retrieval but is not temporally close",
            )
        return self._component(
            "temporal_proximity",
            QualityLevel.WEAK,
            "Publication metadata occurs after retrieval",
        )

    def _consistency_component(self, consistent: bool | None) -> QualityComponent:
        if consistent is True:
            return self._component(
                "consistency_with_stronger_evidence",
                QualityLevel.STRONG,
                "Source is consistent with stronger evidence",
            )
        if consistent is False:
            return self._component(
                "consistency_with_stronger_evidence",
                QualityLevel.WEAK,
                "Source conflicts with stronger evidence",
            )
        return self._component(
            "consistency_with_stronger_evidence",
            QualityLevel.UNKNOWN,
            "No stronger-evidence consistency assessment is available",
        )
