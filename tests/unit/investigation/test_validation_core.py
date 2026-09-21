from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import Claim, ClaimEvidenceRelation
from marketpulse.investigation.domain.enums import (
    ArtifactType,
    ClaimImportance,
    ClaimType,
    ConflictResolutionStatus,
    ConflictType,
    EntailmentStatus,
    ImpactSubtype,
    ParseStatus,
    RelationStance,
    ResearchGapType,
    SemanticJudgmentStatus,
    SourceType,
    ValidationStatus,
)
from marketpulse.investigation.domain.sources import (
    DocumentArtifact,
    Evidence,
    Source,
    SourceSnapshot,
)
from marketpulse.investigation.ingestion.locators import make_text_locator
from marketpulse.investigation.validation import (
    AtomicityAssessment,
    ClaimNormalizationProposal,
    ClaimNormalizer,
    ConflictObservation,
    EvidenceIntegrityValidator,
    IntegrityErrorCode,
    RecognizedArtifactVersions,
    SemanticJudgment,
    ValidationPolicy,
    ValidationRequest,
    replayed_judgment,
)
from marketpulse.investigation.validation.profiles import PROFILES

NOW = datetime(2026, 9, 22, tzinfo=UTC)


@dataclass(frozen=True)
class Bundle:
    source: Source
    snapshot: SourceSnapshot
    artifact: DocumentArtifact
    evidence: Evidence
    relation: ClaimEvidenceRelation
    judgment: SemanticJudgment


def _claim(
    claim_type: ClaimType,
    *,
    claim_id: str = "C-1",
    statement: str = "NTSB stated X",
    qualifiers: dict[str, object] | None = None,
    importance: ClaimImportance = ClaimImportance.HIGH,
    critical: bool = False,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        investigation_id="I-1",
        run_id="RUN-1",
        statement=statement,
        claim_type=claim_type,
        qualifiers=qualifiers or {},
        importance=importance,
        is_critical=critical,
        created_at=NOW,
        updated_at=NOW,
    )


def _bundle(
    blobs: LocalContentAddressedBlobStorage,
    claim: Claim,
    index: int,
    *,
    text: str,
    judgment: SemanticJudgmentStatus = SemanticJudgmentStatus.ENTAILS,
    semantic_confidence: float = 0.9,
    official: bool = False,
    first_hand: bool = False,
    source_type: SourceType = SourceType.NEWS,
    origin_source_id: str | None = None,
    syndication_cluster_id: str | None = None,
    provenance: dict[str, object] | None = None,
    evidence_content: str | None = None,
) -> Bundle:
    source_id = f"S-{index}"
    snapshot_id = f"SS-{index}"
    artifact_id = f"A-{index}"
    evidence_id = f"E-{index}"
    stored = blobs.put_bytes(text.encode())
    source = Source(
        source_id=source_id,
        investigation_id=claim.investigation_id,
        canonical_url=f"https://source-{index}.example.test/item",
        title=f"Source {index}",
        publisher=f"Publisher {index}",
        organization=f"Organization {index}" if official else None,
        source_type=source_type,
        is_official=official,
        is_first_hand=first_hand,
        author=f"Author {index}",
        published_at=NOW,
        discovered_at=NOW,
        origin_source_id=origin_source_id,
        syndication_cluster_id=syndication_cluster_id,
    )
    snapshot = SourceSnapshot(
        snapshot_id=snapshot_id,
        source_id=source_id,
        run_id=claim.run_id,
        retrieved_at=NOW,
        raw_blob_ref=stored.ref,
        raw_sha256=stored.ref.sha256,
        cleaned_blob_ref=stored.ref,
        cleaned_sha256=stored.ref.sha256,
        mime_type="text/plain",
        encoding="utf-8",
        content_size=len(text.encode()),
        http_status=200,
        parse_status=ParseStatus.PARSED,
        parser_name="fixture-parser",
        parser_version="1",
        normalizer_version="1",
        evidence_eligible=True,
        provenance=provenance
        or {
            "methodology": "documented method",
            "data_provenance": "direct record",
            "speculation_level": 0.1,
            "explicit_uncertainty": True,
        },
    )
    artifact = DocumentArtifact(
        artifact_id=artifact_id,
        snapshot_id=snapshot_id,
        artifact_type=ArtifactType.PLAIN_TEXT,
        blob_ref=stored.ref,
        sha256=stored.ref.sha256,
        processor_name="fixture-processor",
        processor_version="1",
        created_at=NOW,
    )
    content = evidence_content if evidence_content is not None else text
    evidence = Evidence(
        evidence_id=evidence_id,
        run_id=claim.run_id,
        snapshot_id=snapshot_id,
        artifact_id=artifact_id,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        locator=make_text_locator(text, 0, len(text)),
        event_time=NOW,
        extracted_at=NOW,
        extractor_name="fixture",
        extractor_version="1",
    )
    relation = ClaimEvidenceRelation(
        relation_id=f"REL-{index}",
        claim_id=claim.claim_id,
        evidence_id=evidence_id,
        stance=(
            RelationStance.CONTRADICTS
            if judgment is SemanticJudgmentStatus.CONTRADICTS
            else RelationStance.SUPPORTS
        ),
        entailment_status=EntailmentStatus.PENDING,
        created_at=NOW,
    )
    semantic = SemanticJudgment(
        judgment_id=f"SJ-{claim.claim_id}-{index}",
        run_id=claim.run_id,
        claim_id=claim.claim_id,
        evidence_id=evidence_id,
        judgment=judgment,
        reason=f"fixture judgment {index}",
        semantic_confidence=semantic_confidence,
        model_call_ref=f"MC-{index}",
        schema_version="1",
        created_at=NOW,
    )
    return Bundle(source, snapshot, artifact, evidence, relation, semantic)


def _policy(blobs: LocalContentAddressedBlobStorage) -> ValidationPolicy:
    return ValidationPolicy(
        integrity=EvidenceIntegrityValidator(
            blobs=blobs,
            recognized_versions=RecognizedArtifactVersions(
                snapshot_parsers=frozenset({("fixture-parser", "1", "1")}),
                artifact_processors=frozenset({("fixture-processor", "1")}),
            ),
        )
    )


def _request(
    claim: Claim,
    bundles: tuple[Bundle, ...],
    *,
    validation_id: str = "V-1",
    created_at: datetime = NOW,
    observations: tuple[ConflictObservation, ...] = (),
    judgments: tuple[SemanticJudgment, ...] | None = None,
) -> ValidationRequest:
    return ValidationRequest(
        validation_id=validation_id,
        created_at=created_at,
        claim=claim,
        relations=tuple(item.relation for item in bundles),
        evidence=tuple(item.evidence for item in bundles),
        snapshots=tuple(item.snapshot for item in bundles),
        artifacts=tuple(item.artifact for item in bundles),
        sources=tuple(item.source for item in bundles),
        semantic_judgments=(
            judgments if judgments is not None else tuple(item.judgment for item in bundles)
        ),
        conflict_observations=observations,
    )


def _official_bundle(
    blobs: LocalContentAddressedBlobStorage,
    claim: Claim,
    index: int = 1,
    text: str = "NTSB stated X",
) -> Bundle:
    return _bundle(
        blobs,
        claim,
        index,
        text=text,
        official=True,
        first_hand=True,
        source_type=SourceType.OFFICIAL_REPORT,
    )


def test_statement_verifies_attribution_but_not_objective_event(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    statement = _claim(ClaimType.STATEMENT)
    statement_bundle = _official_bundle(blobs, statement)
    statement_result = _policy(blobs).validate(_request(statement, (statement_bundle,)))
    assert statement_result.result.status is ValidationStatus.VERIFIED

    objective = _claim(
        ClaimType.EVENT_FACT,
        claim_id="C-2",
        statement="X objectively happened",
    )
    objective_bundle = _official_bundle(blobs, objective, text="NTSB stated X")
    objective_result = _policy(blobs).validate(_request(objective, (objective_bundle,)))
    assert objective_result.result.status is ValidationStatus.UNVERIFIED
    assert ResearchGapType.INSUFFICIENT_INDEPENDENCE in {
        item.gap_type for item in objective_result.research_gaps
    }


def test_single_official_causal_assertion_without_mechanism_is_not_verified(
    tmp_path: Path,
) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.CAUSAL,
        statement="X caused Y",
        qualifiers={"temporal_ordering": True},
    )
    result = _policy(blobs).validate(_request(claim, (_official_bundle(blobs, claim),)))
    assert result.result.status is ValidationStatus.UNVERIFIED
    assert {
        ResearchGapType.MISSING_MECHANISM,
        ResearchGapType.MISSING_CAUSAL_SUPPORT,
        ResearchGapType.INSUFFICIENT_INDEPENDENCE,
    } <= {item.gap_type for item in result.research_gaps}


def test_five_syndicated_copies_count_as_one_family(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.EVENT_FACT)
    bundles = tuple(
        _bundle(
            blobs,
            claim,
            index,
            text=f"Syndicated fact {index}",
            first_hand=index == 1,
            source_type=SourceType.NEWS,
            origin_source_id="S-1" if index > 1 else None,
            syndication_cluster_id="wire-1",
        )
        for index in range(1, 6)
    )
    outcome = _policy(blobs).validate(_request(claim, bundles))
    assert outcome.independence.source_count == 5
    assert outcome.independence.independent_family_count == 1
    assert len(outcome.independence.duplicate_or_syndicated_members[0]) == 5


def test_quantitative_conflict_is_not_averaged_and_can_be_high_confidence_disputed(
    tmp_path: Path,
) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.QUANTITATIVE,
        qualifiers={
            "value": 1500,
            "unit": "people",
            "time": "2026-09-21",
            "scope": "city",
            "definition": "evacuated",
            "methodology": "official counts",
        },
    )
    bundles = (
        _official_bundle(blobs, claim, 1, "1500 evacuated"),
        _bundle(blobs, claim, 2, text="2000 evacuated", first_hand=True),
    )
    observations = (
        ConflictObservation(
            claim_id=claim.claim_id,
            evidence_id="E-1",
            statement="1500 evacuated",
            conflict_type=ConflictType.QUANTITATIVE,
            numeric_value=1500,
            unit="people",
            scope="city",
            definition="evacuated",
            report_stage="FINAL",
        ),
        ConflictObservation(
            claim_id=claim.claim_id,
            evidence_id="E-2",
            statement="2000 evacuated",
            conflict_type=ConflictType.QUANTITATIVE,
            numeric_value=2000,
            unit="people",
            scope="city",
            definition="evacuated",
            report_stage="FINAL",
        ),
    )
    outcome = _policy(blobs).validate(_request(claim, bundles, observations=observations))
    assert outcome.result.status is ValidationStatus.DISPUTED
    assert outcome.result.confidence == 0.9
    assert outcome.conflict_updates[0].resolution_status is ConflictResolutionStatus.UNRESOLVED
    assert {item["value"] for item in outcome.conflict_updates[0].competing_values} == {
        1500,
        2000,
    }


def test_strong_direct_contradiction_blocks_three_supporting_votes(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.EVENT_FACT)
    supports = tuple(
        _bundle(blobs, claim, index, text=f"support {index}", first_hand=True)
        for index in range(1, 4)
    )
    contradiction = _bundle(
        blobs,
        claim,
        4,
        text="direct contradiction",
        judgment=SemanticJudgmentStatus.CONTRADICTS,
        semantic_confidence=0.95,
        official=True,
        first_hand=True,
        source_type=SourceType.OFFICIAL_REPORT,
    )
    observation = ConflictObservation(
        claim_id=claim.claim_id,
        evidence_id="E-4",
        statement="direct contradiction",
        conflict_type=ConflictType.OTHER,
        directness=0.95,
        specificity=0.95,
    )
    outcome = _policy(blobs).validate(
        _request(claim, (*supports, contradiction), observations=(observation,))
    )
    assert outcome.strong_contradiction.triggered is True
    assert outcome.result.status is ValidationStatus.DISPUTED


def test_reported_symptom_does_not_satisfy_causal_impact(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    reported = _claim(
        ClaimType.IMPACT,
        qualifiers={"impact_subtype": ImpactSubtype.REPORTED_SYMPTOM.value},
    )
    reported_bundle = _official_bundle(blobs, reported, text="Residents reported headaches")
    reported_outcome = _policy(blobs).validate(_request(reported, (reported_bundle,)))
    assert reported_outcome.result.status is ValidationStatus.VERIFIED

    causal = _claim(
        ClaimType.IMPACT,
        claim_id="C-2",
        statement="The derailment caused headaches",
        qualifiers={"impact_subtype": ImpactSubtype.CAUSAL_IMPACT.value},
    )
    causal_bundle = _official_bundle(blobs, causal, text="Residents reported headaches")
    causal_outcome = _policy(blobs).validate(_request(causal, (causal_bundle,)))
    assert causal_outcome.result.status is ValidationStatus.UNVERIFIED
    assert ResearchGapType.MISSING_MECHANISM in {
        item.gap_type for item in causal_outcome.research_gaps
    }


def test_existing_evidence_with_quote_mismatch_fails_before_sufficiency(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.STATEMENT)
    bundle = _bundle(
        blobs,
        claim,
        1,
        text="actual persisted quote",
        evidence_content="different Evidence content",
        official=True,
        first_hand=True,
        source_type=SourceType.OFFICIAL_REPORT,
    )
    outcome = _policy(blobs).validate(_request(claim, (bundle,)))
    assert outcome.result.status is ValidationStatus.UNVERIFIED
    assert outcome.integrity_results[0].failures[0].code is IntegrityErrorCode.QUOTE_MISMATCH


def test_valid_quote_with_not_relevant_entailment_is_not_verified(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.STATEMENT)
    bundle = _bundle(
        blobs,
        claim,
        1,
        text="valid unrelated quote",
        judgment=SemanticJudgmentStatus.NOT_RELEVANT,
        official=True,
        first_hand=True,
        source_type=SourceType.OFFICIAL_REPORT,
    )
    outcome = _policy(blobs).validate(_request(claim, (bundle,)))
    assert outcome.result.status is ValidationStatus.UNVERIFIED


def test_quantitative_unit_mismatch_is_a_real_conflict(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.QUANTITATIVE,
        qualifiers={
            "value": 10,
            "unit": "distance",
            "time": "2026-09-21",
            "scope": "route",
            "definition": "affected distance",
            "provenance": "measurements",
        },
    )
    bundles = (
        _official_bundle(blobs, claim, 1, "10 miles"),
        _bundle(blobs, claim, 2, text="10 km", first_hand=True),
    )
    observations = tuple(
        ConflictObservation(
            claim_id=claim.claim_id,
            evidence_id=f"E-{index}",
            statement=statement,
            conflict_type=ConflictType.QUANTITATIVE,
            numeric_value=10,
            unit=unit,
        )
        for index, statement, unit in ((1, "10 miles", "miles"), (2, "10 km", "km"))
    )
    outcome = _policy(blobs).validate(_request(claim, bundles, observations=observations))
    conflict = outcome.conflict_updates[0]
    assert conflict.resolution_status is ConflictResolutionStatus.UNRESOLVED
    assert "unit mismatch" in conflict.possible_explanations[0]


def test_preliminary_to_final_number_is_resolved_with_time(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.QUANTITATIVE,
        qualifiers={
            "value": 2000,
            "unit": "people",
            "time": "final",
            "scope": "city",
            "definition": "evacuated",
            "methodology": "updated count",
        },
    )
    bundles = (
        _official_bundle(blobs, claim, 1, "early estimate 1500"),
        _bundle(blobs, claim, 2, text="final count 2000", first_hand=True),
    )
    observations = (
        ConflictObservation(
            claim_id=claim.claim_id,
            evidence_id="E-1",
            statement="early estimate 1500",
            conflict_type=ConflictType.QUANTITATIVE,
            numeric_value=1500,
            unit="people",
            report_time=NOW,
            report_stage="PRELIMINARY",
        ),
        ConflictObservation(
            claim_id=claim.claim_id,
            evidence_id="E-2",
            statement="final count 2000",
            conflict_type=ConflictType.QUANTITATIVE,
            numeric_value=2000,
            unit="people",
            report_time=NOW + timedelta(days=1),
            report_stage="FINAL",
        ),
    )
    outcome = _policy(blobs).validate(_request(claim, bundles, observations=observations))
    assert (
        outcome.conflict_updates[0].resolution_status is ConflictResolutionStatus.RESOLVED_WITH_TIME
    )
    assert outcome.result.status is ValidationStatus.VERIFIED


def test_interested_party_only_attribution_is_not_verified(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.ATTRIBUTION,
        qualifiers={
            "attribution_kind": "LEGAL_RESPONSIBILITY",
            "interested_party_only": True,
            "direct_finding": False,
        },
    )
    bundle = _official_bundle(blobs, claim, text="It was the other party's fault")
    outcome = _policy(blobs).validate(_request(claim, (bundle,)))
    assert outcome.result.status is ValidationStatus.UNVERIFIED
    assert ResearchGapType.ATTRIBUTION_UNDER_SUPPORTED in {
        item.gap_type for item in outcome.research_gaps
    }


def test_analytic_inference_is_capped_at_probable(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.ANALYTIC_INFERENCE,
        qualifiers={"reasoning_basis": "triangulation", "uncertainty": "moderate"},
    )
    bundles = (
        _bundle(blobs, claim, 1, text="support A", first_hand=True),
        _bundle(blobs, claim, 2, text="support B", first_hand=True),
    )
    outcome = _policy(blobs).validate(_request(claim, bundles))
    assert outcome.result.status is ValidationStatus.PROBABLE
    assert outcome.result.claim_type is ClaimType.ANALYTIC_INFERENCE


def test_identical_inputs_have_identical_semantic_content(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.STATEMENT)
    bundle = _official_bundle(blobs, claim)
    policy = _policy(blobs)
    first = policy.validate(_request(claim, (bundle,), validation_id="V-1"))
    second = policy.validate(
        _request(
            claim,
            (bundle,),
            validation_id="V-2",
            created_at=NOW + timedelta(minutes=1),
        )
    )
    assert first.result.input_fingerprint == second.result.input_fingerprint
    assert first.semantic_content_hash == second.semantic_content_hash


def test_replayed_semantic_judgment_is_input_to_fresh_policy(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.EVENT_FACT)
    bundle = _official_bundle(blobs, claim)
    replayed = replayed_judgment(
        bundle.judgment,
        recorded_judgment_ref="fixture:previous-final-status-was-verified",
        replayed_at=NOW + timedelta(minutes=1),
    )
    outcome = _policy(blobs).validate(_request(claim, (bundle,), judgments=(replayed,)))
    assert outcome.result.status is ValidationStatus.UNVERIFIED
    assert replayed.recorded_judgment_ref is not None


def test_integrity_reports_missing_snapshot_artifact_blob_and_version(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.STATEMENT)
    bundle = _official_bundle(blobs, claim)
    validator = _policy(blobs)._integrity  # noqa: SLF001

    missing = validator.validate(
        evidence=bundle.evidence,
        snapshot=None,
        artifact=None,
    )
    assert {item.code for item in missing.failures} == {
        IntegrityErrorCode.MISSING_SNAPSHOT,
        IntegrityErrorCode.MISSING_ARTIFACT,
    }

    unknown_snapshot = bundle.snapshot.model_copy(update={"parser_version": "unknown"})
    unknown = validator.validate(
        evidence=bundle.evidence,
        snapshot=unknown_snapshot,
        artifact=bundle.artifact,
    )
    assert IntegrityErrorCode.UNRECOGNIZED_VERSION in {item.code for item in unknown.failures}

    absent_ref = BlobRef("f" * 64)
    absent_artifact = bundle.artifact.model_copy(
        update={"blob_ref": absent_ref, "sha256": absent_ref.sha256}
    )
    absent = validator.validate(
        evidence=bundle.evidence,
        snapshot=bundle.snapshot,
        artifact=absent_artifact,
    )
    assert absent.failures[0].code is IntegrityErrorCode.BLOB_NOT_FOUND


def test_normalization_rejects_compound_claim_and_profiles_are_complete() -> None:
    result = ClaimNormalizer().normalize(
        ClaimNormalizationProposal(
            canonical_statement="A happened and caused B",
            entity_qualifiers={"subject": "A"},
            time_qualifiers={"time": "2026"},
            scope_qualifiers={"scope": "city"},
            claim_type=ClaimType.CAUSAL,
            importance=ClaimImportance.HIGH,
            critical=True,
            atomicity=AtomicityAssessment(
                is_atomic=False,
                issues=("multiple independently verifiable propositions",),
                proposed_atomic_statements=("A happened", "A caused B"),
            ),
        )
    )
    assert result.accepted is False
    assert set(PROFILES) == set(ClaimType)


def test_institutional_action_with_direct_record_is_verified(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(
        ClaimType.INSTITUTIONAL_ACTION,
        statement="Agency ordered an evacuation",
        qualifiers={
            "actor": "Agency",
            "action": "ordered evacuation",
            "date": "2026-09-22",
            "scope": "city",
        },
    )
    outcome = _policy(blobs).validate(
        _request(claim, (_official_bundle(blobs, claim, text=claim.statement),))
    )
    assert outcome.result.status is ValidationStatus.VERIFIED


def test_source_quality_has_all_dimensions_without_brand_prior(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.EVENT_FACT)
    bundles = (
        _bundle(blobs, claim, 1, text="fact one", first_hand=True),
        _bundle(blobs, claim, 2, text="fact two", first_hand=True),
    )
    outcome = _policy(blobs).validate(_request(claim, bundles))
    expected = {
        "first_hand",
        "official_direct_participant",
        "primary_source",
        "data_provenance",
        "methodology_transparency",
        "named_author_source",
        "temporal_proximity",
        "retransmission_depth",
        "speculation_level",
        "source_independence",
        "explicit_uncertainty",
        "consistency_with_stronger_evidence",
    }
    assert {item.name for item in outcome.quality_assessments[0].components} == expected
    assert outcome.quality_assessments[0].normalized_score == (
        outcome.quality_assessments[1].normalized_score
    )


def test_integrity_distinguishes_locator_snapshot_and_blob_errors(tmp_path: Path) -> None:
    blobs = LocalContentAddressedBlobStorage(tmp_path / "blobs")
    claim = _claim(ClaimType.STATEMENT)
    bundle = _official_bundle(blobs, claim)
    validator = EvidenceIntegrityValidator(
        blobs=blobs,
        recognized_versions=RecognizedArtifactVersions(
            snapshot_parsers=frozenset({("fixture-parser", "1", "1")}),
            artifact_processors=frozenset({("fixture-processor", "1")}),
        ),
    )
    mismatch_artifact = bundle.artifact.model_copy(update={"snapshot_id": "SS-other"})
    mismatch = validator.validate(
        evidence=bundle.evidence,
        snapshot=bundle.snapshot,
        artifact=mismatch_artifact,
    )
    assert mismatch.failures[0].code is IntegrityErrorCode.SNAPSHOT_ARTIFACT_MISMATCH

    locator = bundle.evidence.locator.model_copy(update={"end": len(bundle.evidence.content) + 20})
    out_of_range_evidence = bundle.evidence.model_copy(update={"locator": locator})
    out_of_range = validator.validate(
        evidence=out_of_range_evidence,
        snapshot=bundle.snapshot,
        artifact=bundle.artifact,
    )
    assert out_of_range.failures[0].code is IntegrityErrorCode.LOCATOR_OUT_OF_RANGE

    class CorruptBlobs:
        def exists(self, ref: BlobRef) -> bool:
            return True

        def verify_hash(self, ref: BlobRef) -> bool:
            return False

        def get_bytes(self, ref: BlobRef) -> bytes:
            return b"corrupt"

    corrupt_validator = EvidenceIntegrityValidator(
        blobs=CorruptBlobs(),  # type: ignore[arg-type]
        recognized_versions=RecognizedArtifactVersions(
            snapshot_parsers=frozenset({("fixture-parser", "1", "1")}),
            artifact_processors=frozenset({("fixture-processor", "1")}),
        ),
    )
    corrupt = corrupt_validator.validate(
        evidence=bundle.evidence,
        snapshot=bundle.snapshot,
        artifact=bundle.artifact,
    )
    assert corrupt.failures[0].code is IntegrityErrorCode.BLOB_INTEGRITY_ERROR
