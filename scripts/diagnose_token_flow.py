"""Read-only, hash-checked model usage/context diagnostics for one persisted run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from marketpulse.investigation.recovery import unknown_model_calls


def blob(root: Path, ref: str) -> dict:
    digest = ref.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("invalid blob digest")
    content = (root / digest[:2] / digest[2:4] / digest).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError("blob digest mismatch")
    return json.loads(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--database", default="data/blackboard.db")
    parser.add_argument("--blobs", default="data/investigation-blobs/sha256")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.blobs)
    with sqlite3.connect(f"file:{Path(args.database).as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        budget = dict(
            db.execute("SELECT * FROM inv_run_budgets WHERE run_id=?", (args.run_id,)).fetchone()
        )
        records = db.execute(
            "SELECT * FROM inv_recorded_model_calls WHERE run_id=? ORDER BY recorded_at,call_id",
            (args.run_id,),
        ).fetchall()
        validation_counts = dict(
            db.execute(
                "SELECT validation_status,COUNT(*) FROM inv_claims WHERE run_id=? "
                "GROUP BY validation_status",
                (args.run_id,),
            ).fetchall()
        )
        gap_counts = dict(
            db.execute(
                "SELECT gap_type,COUNT(*) FROM inv_research_gaps WHERE run_id=? "
                "AND status='OPEN' GROUP BY gap_type",
                (args.run_id,),
            ).fetchall()
        )
        reused_pairs = 0
        for row in db.execute(
            "SELECT output_refs FROM inv_execution_steps WHERE run_id=? "
            "AND status='COMPLETED' AND step_type='VALIDATION'",
            (args.run_id,),
        ):
            for ref in json.loads(row["output_refs"]):
                reused_pairs += blob(root, ref).get("reused_semantic_pairs", 0)
        failed_steps = [
            dict(row)
            for row in db.execute(
                "SELECT logical_step_key,status,error_code,retryable FROM inv_execution_steps "
                "WHERE run_id=? AND status='FAILED'",
                (args.run_id,),
            )
        ]
        model_events = []
        for row in db.execute(
            "SELECT event_type,metadata FROM inv_audit_events "
            "WHERE run_id=? AND event_type LIKE 'MODEL_CALL%' ORDER BY created_at",
            (args.run_id,),
        ):
            details = json.loads(row["metadata"])
            model_events.append(
                {
                    "event": row["event_type"],
                    **{
                        k: details[k]
                        for k in (
                            "intent_id",
                            "logical_step_key",
                            "call_site_key",
                            "outcome",
                            "error_code",
                        )
                        if k in details
                    },
                }
            )
        calls = []
        for row in records:
            request = blob(root, row["request_blob_ref"])["request"]
            response = blob(root, row["response_blob_ref"]) if row["response_blob_ref"] else {}
            usage = response.get("usage", {})
            contexts = []
            for message in request.get("messages", []):
                try:
                    contexts.append(json.loads(message["content"])["bounded_context"])
                except (ValueError, KeyError, TypeError):
                    pass
            context = contexts[0] if contexts else {}
            artifacts = context.get("artifacts", [])
            metadata = json.loads(row["metadata"])
            calls.append(
                {
                    "call_id": row["call_id"],
                    "role": (row["prompt_version"] or "").split(":")[-1],
                    "logical_step_key": metadata.get("logical_step_key"),
                    "status": row["status"],
                    "error_code": row["error_code"],
                    "provider_diagnostics": {
                        key: value
                        for key, value in metadata.get("provider_diagnostics", {}).items()
                        if key in {"category", "transport_category", "http_status"}
                    },
                    "input_tokens": usage.get("input_tokens", 0) or 0,
                    "output_tokens": usage.get("output_tokens", 0) or 0,
                    "context_chars": sum(len(m["content"]) for m in request.get("messages", [])),
                    "artifact_chars": sum(len(a.get("excerpt", "")) for a in artifacts),
                    "artifact_keys": [a["artifact_key"] for a in artifacts],
                    "context_field_chars": {
                        key: len(json.dumps(value, ensure_ascii=False))
                        for key, value in context.items()
                    },
                    "claims": len(context.get("claims", [])),
                    "evidence": len(context.get("evidence", [])),
                    "repair": len(request.get("messages", [])) > 2,
                }
            )
    engine = create_engine(f"sqlite:///file:{Path(args.database).as_posix()}?mode=ro&uri=true")
    with Session(engine) as session:
        unknown = unknown_model_calls(session, args.run_id)
    engine.dispose()
    groups = defaultdict(Counter)
    repeated = Counter()
    for call in calls:
        group = groups[call["role"]]
        for field in ("input_tokens", "output_tokens", "context_chars", "artifact_chars"):
            group[field] += call[field]
        group["calls"] += 1
        group["repair_calls"] += int(call["repair"])
        repeated.update(call["artifact_keys"])
    output = {
        "run_id": args.run_id,
        "budget": budget,
        "failed_steps": failed_steps,
        "model_events": model_events,
        "validation_statuses": validation_counts,
        "open_gap_types": gap_counts,
        "reused_semantic_pairs": reused_pairs,
        "unknown_model_calls": unknown,
        "roles": dict(groups),
        "calls": calls,
        "repeated_artifact_views": {k: v for k, v in repeated.items() if v > 1},
        "recorded_tokens": sum(c["input_tokens"] + c["output_tokens"] for c in calls),
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=True, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in output.items()
                if k not in {"calls", "repeated_artifact_views", "model_events"}
            },
            indent=2,
        )
    )
    print("Repeated artifact views:", len(output["repeated_artifact_views"]))


if __name__ == "__main__":
    main()
