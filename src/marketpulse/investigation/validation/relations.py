"""Project immutable proposals through a specific validation, never mutate history."""

from __future__ import annotations

from marketpulse.investigation.domain.claims import ClaimEvidenceRelation, ValidationResult
from marketpulse.investigation.domain.enums import EntailmentStatus


def validated_relation(
    relation: ClaimEvidenceRelation, validation: ValidationResult
) -> ClaimEvidenceRelation:
    if relation.claim_id != validation.claim_id:
        raise ValueError("relation belongs to a different claim")
    basis = validation.validation_basis_payload
    judgments = basis.get("semantic_judgments", {})
    valid_ids = basis.get("integrity_valid_evidence_ids", [])
    status = EntailmentStatus.PENDING
    if isinstance(judgments, dict) and isinstance(valid_ids, list):
        if relation.evidence_id in valid_ids:
            status = {
                "ENTAILS": EntailmentStatus.ENTAILED,
                "PARTIALLY_SUPPORTS": EntailmentStatus.UNCERTAIN,
                "CONTRADICTS": EntailmentStatus.CONTRADICTED,
                "NOT_RELEVANT": EntailmentStatus.NOT_ENTAILED,
                "UNCERTAIN": EntailmentStatus.UNCERTAIN,
            }.get(str(judgments.get(relation.evidence_id)), EntailmentStatus.PENDING)
    return relation.model_copy(update={"entailment_status": status})
