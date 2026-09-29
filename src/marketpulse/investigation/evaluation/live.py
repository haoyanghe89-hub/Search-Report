"""Read-only metrics export for separately executed LIVE pilot runs."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.infrastructure.storage.ports import BlobStoragePort
from marketpulse.investigation.domain.enums import ExternalCallStatus, RunMode
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import (
    ClaimRow,
    InvestigationRunRow,
    RecordedModelCallRow,
    RecordedToolCallRow,
    RunBudgetRow,
    SourceSnapshotRow,
)


def summarize_live_run(
    sessions: sessionmaker[Session],
    blobs: BlobStoragePort,
    run_id: str,
) -> dict[str, Any]:
    with sessions() as session:
        run = session.get(InvestigationRunRow, run_id)
        if run is None or run.mode is not RunMode.LIVE:
            raise ValueError("metrics require an existing independent LIVE run")
        budget = session.get(RunBudgetRow, run_id)
        if budget is None:
            raise ValueError("run has no budget record")
        tools = session.scalars(
            select(RecordedToolCallRow).where(
                RecordedToolCallRow.run_id == run_id,
            )
        ).all()
        models = session.scalars(
            select(RecordedModelCallRow).where(
                RecordedModelCallRow.run_id == run_id,
            )
        ).all()
        snapshots = session.scalars(
            select(SourceSnapshotRow).where(
                SourceSnapshotRow.run_id == run_id,
            )
        ).all()
        claims = session.scalars(select(ClaimRow).where(ClaimRow.run_id == run_id)).all()
        urls: set[str] = set()
        fetched = 0
        missing_payloads = []
        input_tokens = output_tokens = 0
        missing_usage = 0
        for call in tools:
            if call.status is not ExternalCallStatus.SUCCESS or not call.response_blob_ref:
                continue
            try:
                payload = json.loads(blobs.get_bytes(BlobRef.from_uri(call.response_blob_ref)))
            except (OSError, ValueError, RuntimeError):
                missing_payloads.append(call.call_id)
                continue
            if call.operation == "search":
                urls.update(item["url"] for item in payload.get("items", []))
            elif call.operation == "fetch" and 200 <= payload.get("status_code", 0) < 300:
                fetched += 1
        for model_call in models:
            if not model_call.response_blob_ref:
                missing_usage += 1
                continue
            try:
                payload = json.loads(
                    blobs.get_bytes(BlobRef.from_uri(model_call.response_blob_ref))
                )
            except (OSError, ValueError, RuntimeError):
                missing_payloads.append(model_call.call_id)
                missing_usage += 1
                continue
            usage = payload.get("usage", {})
            if usage.get("input_tokens") is None or usage.get("output_tokens") is None:
                missing_usage += 1
            input_tokens += usage.get("input_tokens") or 0
            output_tokens += usage.get("output_tokens") or 0
        return {
            "schema_version": "live-eval-v1",
            "run_id": run_id,
            "workflow_version": run.workflow_version,
            "status": run.status.value,
            "termination_reason": run.interruption_reason,
            "search_calls_reserved": budget.search_calls_used,
            "search_unique_urls": len(urls),
            "search_domains": sorted({urlsplit(url).netloc for url in urls}),
            "fetch_calls_reserved": budget.fetch_calls_used,
            "fetch_http_successes": fetched,
            "fetch_success_rate": fetched / budget.fetch_calls_used
            if budget.fetch_calls_used
            else None,
            "evidence_eligible_snapshots": sum(s.evidence_eligible for s in snapshots),
            "parse_statuses": dict(Counter(s.parse_status.value for s in snapshots)),
            "model_calls_reserved": budget.model_calls_used,
            "recorded_input_tokens": input_tokens,
            "recorded_output_tokens": output_tokens,
            "calls_missing_usage": missing_usage,
            "unrecorded_model_reservations": max(0, budget.model_calls_used - len(models)),
            "cost": None,
            "cost_note": "Reconcile provider billing; missing usage is not zero cost.",
            "active_time_ms": budget.consumed_wall_time_ms,
            "elapsed_seconds": (run.completed_at - run.started_at).total_seconds()
            if run.completed_at and run.started_at
            else None,
            "claim_statuses": dict(Counter(c.validation_status.value for c in claims)),
            "missing_payloads": missing_payloads,
            "human_review": {
                "search_coverage": None,
                "conclusion_correctness": None,
                "unsupported_conclusions": None,
                "notes": None,
            },
            "scope": "Operational metrics; claim statuses are not human correctness judgments.",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--blob-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = create_investigation_engine(args.database_url)
    try:
        result = summarize_live_run(
            create_session_factory(engine),
            LocalContentAddressedBlobStorage(args.blob_root),
            args.run_id,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
