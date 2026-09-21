from __future__ import annotations

from marketpulse.domain.evidence import (
    CoverageSummary,
    EvidenceBundle,
    EvidenceClaim,
    PageEvidence,
    Source,
    SourceType,
)


class EvidenceStore:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._claims: list[EvidenceClaim] = []
        self._claim_keys: set[tuple[str, str]] = set()
        self._warnings: list[str] = []

    def add(self, page: PageEvidence) -> None:
        url_key = str(page.source.url).rstrip("/")
        if url_key in self._sources:
            return
        self._sources[url_key] = page.source
        for claim in page.claims:
            key = (claim.claim_type, claim.statement.casefold())
            if key not in self._claim_keys:
                self._claim_keys.add(key)
                self._claims.append(claim)

    def warn(self, message: str) -> None:
        if message not in self._warnings:
            self._warnings.append(message)

    def bundle(self) -> EvidenceBundle:
        return EvidenceBundle(
            sources=list(self._sources.values()),
            claims=self._claims,
            warnings=self._warnings,
        )

    def coverage(self) -> CoverageSummary:
        official = sum(
            source.source_type == SourceType.OFFICIAL for source in self._sources.values()
        )
        pricing = sum(claim.claim_type == "pricing" for claim in self._claims)
        count = len(self._sources)
        return CoverageSummary(
            unique_sources=count,
            official_sources=official,
            claim_count=len(self._claims),
            pricing_claims=pricing,
            low_coverage=count < 8 or official < 3,
        )
