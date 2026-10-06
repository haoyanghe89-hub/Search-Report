"""Offline, read-only diagnosis of persisted profile requirements for one run."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from marketpulse.adapters.investigation_search import PublicSearchPortAdapter
from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.claims import Claim, ConflictSet
from marketpulse.investigation.domain.enums import SemanticJudgmentStatus, SourceType
from marketpulse.investigation.domain.sources import Source, SourceSnapshot
from marketpulse.investigation.validation.independence import SourceIndependencePolicy
from marketpulse.investigation.validation.lineage import SourceLineageResolver
from marketpulse.investigation.validation.policy import ValidationPolicy
from marketpulse.investigation.validation.profiles import PROFILES, ProfileContext
from marketpulse.investigation.validation.quality import SourceQualityAssessor


def diagnose(database: Path, run_id: str, output: Path, reassess: bool = False) -> None:
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")

        def rows(table: str, field: str = "run_id", value: str = run_id) -> list[dict]:
            return [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE {field}=?", (value,))]

        def decoded(row: dict) -> dict:
            return {
                k: json.loads(v)
                if k
                in {
                    "qualifiers",
                    "source_quality_summary",
                    "validation_basis_payload",
                    "conflict_set_refs",
                    "claim_ids",
                    "evidence_ids",
                    "possible_causes",
                    "competing_values",
                    "possible_explanations",
                    "provenance",
                }
                and isinstance(v, str)
                else v
                for k, v in row.items()
            }

        claims = [Claim.model_validate(decoded(r)) for r in rows("inv_claims")]
        validations = {r["validation_id"]: decoded(r) for r in rows("inv_validation_results")}
        evidence = {r["evidence_id"]: r for r in rows("inv_evidence")}
        snapshots = {r["snapshot_id"]: r for r in rows("inv_source_snapshots")}
        sources = {
            r["source_id"]: Source.model_validate(decoded(r))
            for r in rows("inv_sources", "investigation_id", claims[0].investigation_id)
        }
        if reassess:
            adapter = PublicSearchPortAdapter(None)
            for key, source in list(sources.items()):
                issuer = adapter._publisher(str(source.canonical_url))
                if issuer:
                    sources[key] = source.model_copy(
                        update={
                            "publisher": issuer,
                            "organization": issuer,
                            "is_official": True,
                            "source_type": SourceType.OFFICIAL_REPORT,
                            "syndication_cluster_id": "issuer:" + issuer,
                        }
                    )
            typed_snapshots = tuple(
                SourceSnapshot.model_validate(
                    {
                        **decoded(r),
                        "raw_blob_ref": BlobRef.from_uri(r["raw_blob_ref"]),
                        "cleaned_blob_ref": BlobRef.from_uri(r["cleaned_blob_ref"])
                        if r["cleaned_blob_ref"]
                        else None,
                    }
                )
                for r in snapshots.values()
            )
            lineage = SourceLineageResolver().resolve(
                sources=tuple(sources.values()), snapshots=typed_snapshots
            )
            families = {f.family_id: f for f in lineage.families}
            quality = {}
            for snapshot in sorted(typed_snapshots, key=lambda s: s.retrieved_at):
                source = sources[snapshot.source_id]
                quality[source.source_id] = SourceQualityAssessor().assess(
                    source=source,
                    snapshot=snapshot,
                    family=families[lineage.source_to_family[source.source_id]],
                )
        conflicts = {
            r["conflict_id"]: ConflictSet.model_validate(
                {
                    **decoded(r),
                    "claim_ids": tuple(
                        x[0]
                        for x in db.execute(
                            "SELECT claim_id FROM inv_conflict_claims WHERE conflict_id=?",
                            (r["conflict_id"],),
                        )
                    ),
                }
            )
            for r in rows("inv_conflict_sets")
        }
        entries = []
        missing_counts: Counter = Counter()
        grade_counts: Counter = Counter()
        alignment_counts: Counter = Counter()
        for claim in claims:
            validation = validations.get(claim.latest_validation_id)
            if validation is None:
                entries.append({"claim_id": claim.claim_id, "not_yet_validated": True})
                continue
            basis = validation["validation_basis_payload"]
            judgments = tuple(
                SimpleNamespace(evidence_id=k, judgment=SemanticJudgmentStatus(v))
                for k, v in basis["semantic_judgments"].items()
            )
            context = ProfileContext(
                claim=claim,
                judgments=judgments,
                evidence_to_source={
                    k: snapshots[v["snapshot_id"]]["source_id"] for k, v in evidence.items()
                },
                source_by_id=sources,
                independence=SimpleNamespace(
                    independent_family_count=basis["independent_family_count"]
                ),
                quality_by_source={
                    k: SimpleNamespace(normalized_score=v)
                    for k, v in basis["quality_scores"].items()
                },
                conflicts=tuple(conflicts[k] for k in basis["unresolved_conflict_ids"]),
                strong_contradiction=SimpleNamespace(triggered=basis["strong_contradiction"]),
            )
            if reassess:
                support = frozenset(
                    j.evidence_id
                    for j in judgments
                    if j.judgment
                    in {SemanticJudgmentStatus.ENTAILS, SemanticJudgmentStatus.PARTIALLY_SUPPORTS}
                )
                independence = SourceIndependencePolicy().assess(
                    evidence=tuple(SimpleNamespace(**r) for r in evidence.values()),
                    eligible_evidence_ids=support,
                    snapshots=typed_snapshots,
                    sources=tuple(sources.values()),
                    lineage=lineage,
                )
                from dataclasses import replace

                context = replace(context, independence=independence, quality_by_source=quality)
            profile = PROFILES[claim.claim_type].evaluate(context)
            missing_counts.update(profile.missing_requirements)
            grade = ValidationPolicy._status(
                profile_status=profile.recommended_status,
                profile_sufficient=profile.sufficient,
                strong=basis["strong_contradiction"],
                conflicts=context.conflicts,
            )
            grade_counts.update([grade.value])
            shared_numbers = sorted(
                set(re.findall(r"\d+(?:\.\d+)?", claim.statement))
                & {
                    n
                    for j in judgments
                    for n in re.findall(r"\d+(?:\.\d+)?", evidence[j.evidence_id]["content"])
                }
            )
            alignment = {}
            for key in profile.missing_requirements:
                finding = "MATERIAL_NOT_DETERMINED_FROM_CAPTURED_QUOTES"
                if key == "qualifier:value" and shared_numbers:
                    finding = "LITERAL_NUMBERS_PRESENT_IN_STATEMENT_AND_QUOTE_BUT_UNSTRUCTURED"
                if (
                    key == "qualifier:unit"
                    and shared_numbers
                    and any("%" in evidence[j.evidence_id]["content"] for j in judgments)
                ):
                    finding = "PERCENT_UNIT_PRESENT_BUT_UNSTRUCTURED"
                if key == "qualifier:definition" and claim.qualifiers.get("metric"):
                    finding = "SUPPLIED_METRIC_ALIAS_NOT_CANONICAL"
                alignment[key] = finding
                alignment_counts.update([finding])
            entries.append(
                {
                    "claim_id": claim.claim_id,
                    "statement": claim.statement,
                    "claim_type": claim.claim_type.value,
                    "qualifiers": claim.qualifiers,
                    "persisted_status": claim.validation_status.value,
                    "profile": profile.model_dump(mode="json"),
                    "candidate_policy_grade": grade.value,
                    "field_alignment": alignment,
                    "shared_literal_numbers": shared_numbers,
                    "reassessed_source_scores": {
                        k: v.normalized_score
                        for k, v in quality.items()
                        if k in basis["quality_scores"]
                    }
                    if reassess
                    else {},
                    "basis": basis,
                    "evidence": [
                        {
                            "evidence_id": j.evidence_id,
                            "judgment": j.judgment.value,
                            "quote": evidence[j.evidence_id]["content"],
                        }
                        for j in judgments
                    ],
                }
            )
        result = {
            "run_id": run_id,
            "captured_at": datetime.now(UTC).isoformat(),
            "status_counts": dict(Counter(c.validation_status.value for c in claims)),
            "claim_count": len(claims),
            "validation_count": len(validations),
            "missing_counts": dict(missing_counts),
            "candidate_grade_counts": dict(grade_counts),
            "field_alignment_counts": dict(alignment_counts),
            "source_metadata_reassessed_in_memory": reassess,
            "claims": entries,
            "sources": [
                {
                    "source_id": s.source_id,
                    "url": str(s.canonical_url),
                    "official": s.is_official,
                    "first_hand": s.is_first_hand,
                    "publisher": s.publisher,
                    "author": s.author,
                }
                for s in sources.values()
            ],
            "note": "Stored semantic/integrity basis only; no model/network/database writes. "
            "Missing qualifiers do not prove absence in unexamined original material.",
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("claim_count", "validation_count", "status_counts", "missing_counts")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--database", type=Path, default=Path("data/blackboard.db"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reassess-source-metadata", action="store_true")
    args = parser.parse_args()
    diagnose(args.database, args.run_id, args.output, args.reassess_source_metadata)
