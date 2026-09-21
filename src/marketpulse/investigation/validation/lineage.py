from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable

from marketpulse.investigation.domain.enums import (
    LineageOriginType,
    LineageResolutionMethod,
)
from marketpulse.investigation.domain.sources import Source, SourceSnapshot
from marketpulse.investigation.validation.models import (
    LineageResolution,
    SourceAttribution,
    SourceFamily,
)


class SourceLineageResolver:
    VERSION = "source-lineage-v1"

    def resolve(
        self,
        *,
        sources: tuple[Source, ...],
        snapshots: tuple[SourceSnapshot, ...] = (),
        explicit_attributions: tuple[SourceAttribution, ...] = (),
    ) -> LineageResolution:
        source_by_id = {source.source_id: source for source in sources}
        parent = {source_id: source_id for source_id in source_by_id}
        edge_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
        edge_basis: dict[tuple[str, str], set[str]] = defaultdict(set)

        def find(source_id: str) -> str:
            root = source_id
            while parent[root] != root:
                root = parent[root]
            while parent[source_id] != source_id:
                next_id = parent[source_id]
                parent[source_id] = root
                source_id = next_id
            return root

        def union(left: str, right: str, kind: str, basis: str) -> None:
            if left not in parent or right not in parent or left == right:
                return
            pair = (left, right) if left < right else (right, left)
            edge_kinds[pair].add(kind)
            edge_basis[pair].add(basis)
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                lower, upper = sorted((left_root, right_root))
                parent[upper] = lower

        for source in sources:
            if source.origin_source_id is not None:
                union(
                    source.source_id,
                    source.origin_source_id,
                    "ORIGIN",
                    f"{source.source_id} declares origin {source.origin_source_id}",
                )

        syndication_members: dict[str, list[str]] = defaultdict(list)
        for source in sources:
            if source.syndication_cluster_id:
                syndication_members[source.syndication_cluster_id].append(source.source_id)
        for cluster_id, members in syndication_members.items():
            ordered = sorted(members)
            for source_id in ordered[1:]:
                union(
                    ordered[0],
                    source_id,
                    "SYNDICATION",
                    f"shared syndication cluster {cluster_id}",
                )

        attributions = list(explicit_attributions)
        for snapshot in snapshots:
            provenance = snapshot.provenance
            single = provenance.get("explicit_attribution_source_id")
            if isinstance(single, str):
                attributions.append(
                    SourceAttribution(
                        source_id=snapshot.source_id,
                        attributed_source_id=single,
                        basis=f"Snapshot {snapshot.snapshot_id} explicit attribution",
                    )
                )
            multiple = provenance.get("attributed_source_ids")
            if isinstance(multiple, list):
                for item in multiple:
                    if isinstance(item, str):
                        attributions.append(
                            SourceAttribution(
                                source_id=snapshot.source_id,
                                attributed_source_id=item,
                                basis=f"Snapshot {snapshot.snapshot_id} attribution list",
                            )
                        )
        for attribution in attributions:
            kind = "SEMANTIC" if attribution.basis.startswith("SEMANTIC:") else "ATTRIBUTION"
            union(
                attribution.source_id,
                attribution.attributed_source_id,
                kind,
                attribution.basis,
            )

        components: dict[str, list[str]] = defaultdict(list)
        for source_id in sorted(source_by_id):
            components[find(source_id)].append(source_id)

        families: list[SourceFamily] = []
        source_to_family: dict[str, str] = {}
        for members in sorted(components.values(), key=lambda item: tuple(item)):
            kinds, bases = self._component_edges(members, edge_kinds, edge_basis)
            family_id = self._family_id(members)
            origin_type = self._origin_type(members, kinds, source_by_id)
            method = self._resolution_method(kinds)
            publishers = self._named_metadata(
                source_by_id[source_id].publisher for source_id in members
            )
            organizations = self._named_metadata(
                source_by_id[source_id].organization for source_id in members
            )
            metadata_basis = [*sorted(bases)]
            if publishers:
                metadata_basis.append(f"publishers: {', '.join(publishers)}")
            if organizations:
                metadata_basis.append(f"organizations: {', '.join(organizations)}")
            if not metadata_basis:
                metadata_basis.append(
                    "no explicit lineage metadata; family remains independent UNKNOWN"
                )
            confidence = (
                0.95
                if method is LineageResolutionMethod.DETERMINISTIC
                else 0.7
                if method is LineageResolutionMethod.SEMANTIC_ASSISTED
                else 0.5
            )
            family = SourceFamily(
                family_id=family_id,
                origin_type=origin_type,
                member_source_ids=tuple(members),
                independence_basis=tuple(metadata_basis),
                confidence=confidence,
                resolution_method=method,
            )
            families.append(family)
            for source_id in members:
                source_to_family[source_id] = family_id

        return LineageResolution(
            version=self.VERSION,
            families=tuple(families),
            source_to_family=source_to_family,
        )

    @staticmethod
    def _component_edges(
        members: list[str],
        edge_kinds: dict[tuple[str, str], set[str]],
        edge_basis: dict[tuple[str, str], set[str]],
    ) -> tuple[set[str], set[str]]:
        member_set = set(members)
        kinds: set[str] = set()
        bases: set[str] = set()
        for pair, pair_kinds in edge_kinds.items():
            if set(pair) <= member_set:
                kinds.update(pair_kinds)
                bases.update(edge_basis[pair])
        return kinds, bases

    @staticmethod
    def _origin_type(
        members: list[str],
        kinds: set[str],
        source_by_id: dict[str, Source],
    ) -> LineageOriginType:
        derivative = bool(kinds & {"ORIGIN", "ATTRIBUTION", "SEMANTIC"})
        syndicated = "SYNDICATION" in kinds
        if derivative and syndicated:
            return LineageOriginType.MIXED
        if syndicated:
            return LineageOriginType.SYNDICATED
        if derivative:
            return LineageOriginType.ATTRIBUTED
        if len(members) == 1 and source_by_id[members[0]].is_first_hand:
            return LineageOriginType.ORIGINAL
        return LineageOriginType.UNKNOWN

    @staticmethod
    def _resolution_method(kinds: set[str]) -> LineageResolutionMethod:
        if "SEMANTIC" in kinds:
            return LineageResolutionMethod.SEMANTIC_ASSISTED
        if kinds:
            return LineageResolutionMethod.DETERMINISTIC
        return LineageResolutionMethod.UNKNOWN

    @staticmethod
    def _family_id(members: list[str]) -> str:
        digest = hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:20]
        return f"FAM-{digest}"

    @staticmethod
    def _named_metadata(values: Iterable[str | None]) -> list[str]:
        return sorted({value.strip() for value in values if value and value.strip()})
