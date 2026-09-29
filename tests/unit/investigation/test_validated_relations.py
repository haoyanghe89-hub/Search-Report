from datetime import UTC, datetime

import pytest

from marketpulse.investigation.domain.claims import ClaimEvidenceRelation, ValidationResult
from marketpulse.investigation.validation.relations import validated_relation


@pytest.mark.parametrize(
    ("judgment", "integrity", "expected"),
    [
        (None, True, "PENDING"),
        ("ENTAILS", False, "PENDING"),
        ("ENTAILS", True, "ENTAILED"),
        ("CONTRADICTS", True, "CONTRADICTED"),
        ("NOT_RELEVANT", True, "NOT_ENTAILED"),
        ("PARTIALLY_SUPPORTS", True, "UNCERTAIN"),
    ],
)
def test_latest_validation_controls_relation(judgment, integrity, expected):
    now = datetime.now(UTC)
    relation = ClaimEvidenceRelation(
        relation_id="R",
        claim_id="C",
        evidence_id="E",
        stance="SUPPORTS",
        entailment_status="ENTAILED",
        created_at=now,
    )
    validation = ValidationResult(
        validation_id="V",
        claim_id="C",
        run_id="RUN",
        claim_type="EVENT_FACT",
        profile_version="v1",
        citation_valid=True,
        entailment_result="ENTAILED",
        independent_source_count=1,
        strong_contradiction=False,
        sufficiency_result="sufficient",
        status="VERIFIED",
        confidence=0.85,
        validation_basis="test",
        validation_basis_payload={
            "semantic_judgments": {"E": judgment} if judgment else {},
            "integrity_valid_evidence_ids": ["E"] if integrity else [],
        },
        created_at=now,
    )
    assert validated_relation(relation, validation).entailment_status == expected
    assert relation.entailment_status == "ENTAILED"  # historical proposal is unchanged
