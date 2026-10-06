"""Read-only audit of an isolated LIVE run; no provider requests or credentials."""

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


def audit(directory: Path) -> dict:
    database = (directory / "live.db").resolve(strict=True)
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        run = dict(db.execute("SELECT * FROM inv_runs").fetchone())
        budget = dict(db.execute("SELECT * FROM inv_run_budgets").fetchone())
        claims = [dict(r) for r in db.execute("SELECT * FROM inv_claims")]
        by_type = defaultdict(Counter)
        for claim in claims:
            by_type[claim["claim_type"]][claim["validation_status"]] += 1
        quality = {}
        latest = {}
        for row in db.execute("SELECT * FROM inv_validation_results ORDER BY created_at, rowid"):
            latest[row["claim_id"]] = dict(row)
        missing = defaultdict(Counter)
        for row in latest.values():
            basis = json.loads(row["validation_basis_payload"])
            quality.update(basis.get("quality_scores", {}))
            for line in row["validation_basis"].split("; "):
                if "missing" in line.casefold() or "not met" in line.casefold():
                    missing[row["claim_type"]][line] += 1
        models = [dict(r) for r in db.execute("SELECT * FROM inv_recorded_model_calls")]
        routes = Counter((r["prompt_version"], r["model"], r["status"]) for r in models)
        source_quality = [
            {
                "source_id": row["source_id"],
                "url": row["canonical_url"],
                "title": row["title"],
                "is_official": bool(row["is_official"]),
                "is_first_hand": bool(row["is_first_hand"]),
                "normalized_score": quality[row["source_id"]],
            }
            for row in db.execute("SELECT * FROM inv_sources")
            if row["source_id"] in quality
        ]
        audits = [dict(r) for r in db.execute("SELECT * FROM inv_audit_events")]
        retry_intents = []
        supplements = []
        for row in audits:
            metadata = json.loads(row["metadata"])
            if metadata.get("retry_policy") == "ALLOW_POSSIBLE_DUPLICATE_CHARGE":
                retry_intents.append({"event_id": row["audit_event_id"], **metadata})
            if row["event_type"] == "CLAIM_QUALIFIERS_SUPPLEMENTED":
                supplements.append({"claim_id": row["target_id"], **metadata})
        documents = []
        for snapshot in db.execute(
            "SELECT * FROM inv_source_snapshots WHERE mime_type='application/pdf'"
        ):
            pages = []
            for artifact in db.execute(
                "SELECT * FROM inv_document_artifacts WHERE snapshot_id=? ORDER BY page_number",
                (snapshot["snapshot_id"],),
            ):
                digest = artifact["blob_ref"].rsplit("/", 1)[-1]
                raw = (directory / "blobs/sha256" / digest[:2] / digest[2:4] / digest).read_bytes()
                pages.append(
                    {
                        "artifact_id": artifact["artifact_id"],
                        "page": artifact["page_number"],
                        "chars": len(raw.decode()),
                        "hash_verified": hashlib.sha256(raw).hexdigest() == artifact["sha256"],
                        "evidence_count": db.execute(
                            "SELECT COUNT(*) FROM inv_evidence WHERE artifact_id=?",
                            (artifact["artifact_id"],),
                        ).fetchone()[0],
                    }
                )
            documents.append(
                {
                    "snapshot_id": snapshot["snapshot_id"],
                    "sha256": snapshot["raw_sha256"],
                    "provenance": json.loads(snapshot["provenance"]),
                    "pages": pages,
                }
            )
        reports = [
            dict(r)
            for r in db.execute(
                "SELECT r.report_id,r.report_type,p.release_status FROM inv_reports r "
                "JOIN inv_report_projections p ON p.report_id=r.report_id"
            )
        ]
        return {
            "audited_at": datetime.now(UTC).isoformat(),
            "run": run,
            "budget": budget,
            "counts": {
                "sources": db.execute("SELECT COUNT(*) FROM inv_sources").fetchone()[0],
                "eligible_sources": db.execute(
                    "SELECT COUNT(DISTINCT source_id) FROM inv_source_snapshots "
                    "WHERE evidence_eligible=1"
                ).fetchone()[0],
                "evidence": db.execute("SELECT COUNT(*) FROM inv_evidence").fetchone()[0],
                "claims": len(claims),
            },
            "statuses": dict(Counter(c["validation_status"] for c in claims)),
            "by_type": {t: dict(v) for t, v in by_type.items()},
            "missing_by_type": {t: dict(v) for t, v in missing.items()},
            "quality_scores": quality,
            "source_quality": source_quality,
            "model_routes": [
                {"role": p, "model": m, "status": s, "count": n} for (p, m, s), n in routes.items()
            ],
            "semantic_statuses": dict(
                db.execute(
                    "SELECT judgment,COUNT(*) FROM inv_semantic_judgments GROUP BY judgment"
                ).fetchall()
            ),
            "retry_intents": retry_intents,
            "qualifier_supplements": supplements,
            "pdf_documents": documents,
            "reports": reports,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("counts", "statuses", "reports")}, ensure_ascii=False))
