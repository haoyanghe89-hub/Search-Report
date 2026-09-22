from __future__ import annotations

from datetime import UTC, datetime, timedelta

from marketpulse.investigation.reporting.hashing import canonical_hash
from marketpulse.investigation.reporting.models import (
    CitationSemanticIdentity,
    ReportInputSemanticPayload,
    ReportInputSnapshot,
    SnapshotClaim,
    SnapshotEvidence,
    SnapshotRuntimeReferences,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _payload(*, statement: str = "The event occurred.") -> ReportInputSemanticPayload:
    return ReportInputSemanticPayload(
        schema_version="phase5-report-input-v1",
        validation_policy_version="phase4-validation-v1",
        investigation_key="investigation:public-event",
        terminal_run_status="READY_FOR_REPORT",
        questions=("What happened?",),
        claims=(
            SnapshotClaim(
                stable_key="claim:event-occurred",
                semantic_hash=HASH_A,
                statement=statement,
                claim_type="EVENT_FACT",
                validation_status="VERIFIED",
                confidence=0.97,
                validation_semantic_hash=HASH_B,
                importance="HIGH",
                is_critical=True,
            ),
        ),
        evidence=(
            SnapshotEvidence(
                stable_key="evidence:official-record",
                semantic_hash=HASH_B,
                content_hash=HASH_C,
                artifact_content_hash=HASH_A,
                snapshot_content_hash=HASH_B,
                source_semantic_key="source:agency:record",
            ),
        ),
    )


def test_canonical_hash_is_mapping_and_set_order_independent() -> None:
    left = {"b": [2, 1], "a": {"z", "x"}}
    right = {"a": {"x", "z"}, "b": [2, 1]}

    assert canonical_hash("test-domain", left) == canonical_hash("test-domain", right)


def test_report_input_hash_excludes_runtime_ids_and_timestamps() -> None:
    payload = _payload()
    first = ReportInputSnapshot.build(
        snapshot_id="SNAP-1",
        investigation_id="INV-1",
        run_id="RUN-LIVE",
        run_mode="LIVE",
        assembled_at=NOW,
        semantic_payload=payload,
        runtime_references=SnapshotRuntimeReferences(
            claim_ids={"claim:event-occurred": "CLAIM-1"},
            evidence_ids={"evidence:official-record": "EVIDENCE-1"},
        ),
    )
    replay = ReportInputSnapshot.build(
        snapshot_id="SNAP-99",
        investigation_id="INV-99",
        run_id="RUN-REPLAY",
        run_mode="REPLAY",
        assembled_at=NOW + timedelta(days=2),
        semantic_payload=payload,
        runtime_references=SnapshotRuntimeReferences(
            claim_ids={"claim:event-occurred": "CLAIM-900"},
            evidence_ids={"evidence:official-record": "EVIDENCE-900"},
        ),
    )

    assert first.snapshot_hash == replay.snapshot_hash
    assert first.claim_set_hash == replay.claim_set_hash
    assert first.source_state_fingerprint == replay.source_state_fingerprint


def test_material_semantic_change_changes_snapshot_hash() -> None:
    original = ReportInputSnapshot.build(
        snapshot_id="SNAP-1",
        investigation_id="INV-1",
        run_id="RUN-1",
        run_mode="LIVE",
        assembled_at=NOW,
        semantic_payload=_payload(),
    )
    changed = ReportInputSnapshot.build(
        snapshot_id="SNAP-2",
        investigation_id="INV-1",
        run_id="RUN-2",
        run_mode="LIVE",
        assembled_at=NOW,
        semantic_payload=_payload(statement="The event did not occur."),
    )

    assert original.snapshot_hash != changed.snapshot_hash
    assert original.claim_set_hash != changed.claim_set_hash


def test_citation_semantic_hash_excludes_runtime_ids_and_display_ordinal() -> None:
    semantic = CitationSemanticIdentity(
        report_input_snapshot_hash=HASH_A,
        claim_set_hash=HASH_B,
        section_key="VERIFIED_FINDINGS",
        unit_key="finding-1",
        claim_semantic_hash=HASH_A,
        validation_semantic_hash=HASH_B,
        relation_semantics="SUPPORTS:ENTAILED",
        evidence_semantic_hash=HASH_C,
        canonical_locator={"kind": "TEXT_RANGE", "start": 0, "end": 19},
        resolved_quote_hash=HASH_A,
        artifact_content_hash=HASH_B,
        snapshot_content_hash=HASH_C,
        source_semantic_identity="source:agency:record",
        entailment_judgment="ENTAILED",
        entailment_version="semantic-entailment-v1",
        schema_version="citation-v1",
    )

    assert semantic.semantic_hash == semantic.model_copy().semantic_hash
    assert "citation_id" not in semantic.semantic_hash_payload()
    assert "display_ordinal" not in semantic.semantic_hash_payload()
