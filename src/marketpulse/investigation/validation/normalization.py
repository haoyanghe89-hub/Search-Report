from __future__ import annotations

from pydantic import JsonValue

from marketpulse.investigation.validation.models import (
    ClaimNormalizationProposal,
    ClaimNormalizationResult,
)


class ClaimNormalizer:
    """Validates a semantic normalization proposal; it is not a general NLP parser."""

    def normalize(self, proposal: ClaimNormalizationProposal) -> ClaimNormalizationResult:
        reasons: list[str] = []
        canonical = " ".join(proposal.canonical_statement.split())
        if canonical != proposal.canonical_statement.strip():
            reasons.append("canonical statement must use normalized whitespace")
        if not proposal.atomicity.is_atomic:
            reasons.append("compound Claim must be split before validation")
        if proposal.atomicity.issues and proposal.atomicity.is_atomic:
            reasons.append("atomic proposal cannot retain atomicity issues")
        qualifiers: dict[str, JsonValue] = {
            "entity": proposal.entity_qualifiers,
            "time": proposal.time_qualifiers,
            "scope": proposal.scope_qualifiers,
        }
        return ClaimNormalizationResult(
            accepted=not reasons,
            canonical_statement=canonical,
            qualifiers=qualifiers,
            claim_type=proposal.claim_type,
            importance=proposal.importance,
            critical=proposal.critical,
            atomicity=proposal.atomicity,
            rejection_reasons=tuple(reasons),
        )
