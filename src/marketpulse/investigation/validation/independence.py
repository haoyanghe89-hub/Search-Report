from __future__ import annotations

from marketpulse.investigation.domain.enums import SourceType
from marketpulse.investigation.domain.sources import Evidence, Source, SourceSnapshot
from marketpulse.investigation.validation.models import (
    IndependentEvidenceAssessment,
    LineageResolution,
)

_PRIMARY_TYPES = {
    SourceType.OFFICIAL_REPORT,
    SourceType.OFFICIAL_STATEMENT,
    SourceType.PUBLIC_DATA,
}


class SourceIndependencePolicy:
    def assess(
        self,
        *,
        evidence: tuple[Evidence, ...],
        eligible_evidence_ids: frozenset[str],
        snapshots: tuple[SourceSnapshot, ...],
        sources: tuple[Source, ...],
        lineage: LineageResolution,
    ) -> IndependentEvidenceAssessment:
        snapshot_by_id = {item.snapshot_id: item for item in snapshots}
        source_by_id = {item.source_id: item for item in sources}
        used_source_ids: set[str] = set()
        for item in evidence:
            if item.evidence_id not in eligible_evidence_ids:
                continue
            snapshot = snapshot_by_id.get(item.snapshot_id)
            if snapshot is not None and snapshot.source_id in source_by_id:
                used_source_ids.add(snapshot.source_id)

        family_by_id = {family.family_id: family for family in lineage.families}
        used_family_ids = {
            lineage.source_to_family[source_id]
            for source_id in used_source_ids
            if source_id in lineage.source_to_family
        }
        families = tuple(family_by_id[family_id] for family_id in sorted(used_family_ids))
        duplicates: list[tuple[str, ...]] = []
        primary_families: set[str] = set()
        for family in families:
            used_members = tuple(
                source_id for source_id in family.member_source_ids if source_id in used_source_ids
            )
            if len(used_members) > 1:
                duplicates.append(used_members)
            if any(
                source_by_id[source_id].is_first_hand
                or source_by_id[source_id].source_type in _PRIMARY_TYPES
                for source_id in used_members
            ):
                primary_families.add(family.family_id)

        basis = (
            f"{len(used_source_ids)} eligible Sources collapse to "
            f"{len(families)} provenance families",
            "family count uses explicit lineage and syndication metadata, not URL count",
        )
        return IndependentEvidenceAssessment(
            source_count=len(used_source_ids),
            independent_family_count=len(families),
            families=families,
            duplicate_or_syndicated_members=tuple(duplicates),
            primary_family_count=len(primary_families),
            secondary_independent_family_count=len(families) - len(primary_families),
            basis=basis,
        )
