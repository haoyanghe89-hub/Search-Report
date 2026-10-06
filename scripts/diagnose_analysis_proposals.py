"""Hash-checked analysis outputs and contract differences, without changing a run."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from diagnose_token_flow import blob

from marketpulse.investigation.agents.contracts import (
    AnalysisInput,
    AnalysisProposal,
    validate_agent_proposal,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--database", default="data/blackboard.db")
    parser.add_argument("--blobs", default="data/investigation-blobs/sha256")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    with sqlite3.connect(f"file:{Path(args.database).as_posix()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM inv_recorded_model_calls WHERE run_id=? "
            "AND prompt_version LIKE '%:analyst.analyze' ORDER BY recorded_at",
            (args.run_id,),
        )
        for row in rows:
            request = blob(Path(args.blobs), row["request_blob_ref"])["request"]
            context = json.loads(request["messages"][1]["content"])["bounded_context"]
            entry = {
                "call_id": row["call_id"],
                "status": row["status"],
                "model": row["model"],
                "metadata": json.loads(row["metadata"]),
                "sources": [
                    {k: a[k] for k in ("artifact_key", "source_key", "source_title")}
                    for a in context["artifacts"]
                ],
                "raw_provider_text_available": False,
            }
            if row["response_blob_ref"]:
                output = blob(Path(args.blobs), row["response_blob_ref"])["output"]
                path = args.output / f"{row['call_id']}.json"
                path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                entry["complete_typed_output_file"] = path.name
                try:
                    validate_agent_proposal(
                        AnalysisInput.model_validate(context),
                        AnalysisProposal.model_validate(output),
                    )
                    entry["structure_and_references"] = "PASS"
                except ValueError as error:
                    entry["structure_and_references"] = type(error).__name__
            else:
                entry["limitation"] = (
                    "Invalid provider text was not archived; cannot reconstruct it."
                )
            summaries.append(entry)
    (args.output / "comparison.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"analysis_calls": len(summaries), "output": str(args.output)}))


if __name__ == "__main__":
    main()
