"""Real frozen Task N data -> public HTTP -> durable report/chart evidence.

Uses an isolated read-only backup source, no SDK/model calls or synthetic data.
"""

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from marketpulse.config import Settings
from marketpulse.investigation.server import create_app
from marketpulse.quant.storage.models import DatasetSnapshotRow, InstrumentRow


def verify(source, output):
    root = Path.cwd().resolve()
    source, output = source.resolve(), output.resolve()
    if not source.is_relative_to(root / ".phase3-quant-n"):
        raise ValueError("Task N frozen source required")
    if not output.is_relative_to(root / ".phase3-quant-o") or output.exists():
        raise ValueError("new private Task O destination required")
    output.mkdir(parents=True)
    with sqlite3.connect(f"file:{source / 'metadata.sqlite'}?mode=ro", uri=True) as src:
        with sqlite3.connect(output / "metadata.sqlite") as dst:
            src.backup(dst)
    shutil.copytree(source / "blobs", output / "blobs")
    os.environ["INVESTIGATION_BLOB_ROOT"] = str(output / "blobs")
    os.environ["QUANT_CALL_JOURNAL_ROOT"] = str(output / "calls")
    settings = Settings(
        database_url=SecretStr("sqlite:///" + (output / "metadata.sqlite").as_posix()),
        review_allow_insecure_loopback=True,
    )
    app = create_app(settings=settings)
    results = []
    with TestClient(app) as client:
        service = app.state.quant_runtime.service
        with service.sessions() as session:
            instruments = list(session.scalars(select(InstrumentRow.instrument_id)))
            snapshots = [
                service.store.load(s)
                for s in session.scalars(select(DatasetSnapshotRow.snapshot_id))
            ]
        for ordinal, instrument_id in enumerate(instruments):
            owned = [s for s in snapshots if s.result.request.instruments == (instrument_id,)]
            selected = [
                s
                for s in owned
                if s.result.request.dataset == "daily"
                or s.result.request.normalizer_version == "3-parent-2"
            ]
            selected.append(
                next(
                    s
                    for s in owned
                    if s.result.request.dataset == "calendar"
                    and s.result.request.start.year == 2022
                )
            )
            raw = next(
                s
                for s in selected
                if s.result.request.dataset == "daily" and s.result.request.adjustment == "raw"
            )
            payload = dict(
                instrument=instrument_id,
                date_start=str(raw.result.request.start),
                date_end=str(raw.result.request.end),
                asof=raw.result.request.asof.isoformat(),
                adjustment="raw",
                depth="quick",
                frozen_snapshot_ids=[s.snapshot_id for s in selected],
            )
            response = client.post("/api/quant/runs", json=payload)
            assert response.status_code == 202, response.text
            start = response.json()
            until = time.monotonic() + 300
            while time.monotonic() < until:
                response = client.get("/api/quant/runs/" + start["run_id"])
                assert response.status_code == 200, response.text
                detail = response.json()
                if detail["run"]["status"] == "COMPLETED":
                    break
                assert client.get("/api/health").status_code == 200
                time.sleep(0.5)
            assert detail["run"]["status"] == "COMPLETED" and detail["values"], detail
            assert len(detail["charts"]) == 3, detail["charts"]
            assert all(v["cell_hash"] for v in detail["values"])
            from marketpulse.quant.reporting import load_material

            with service.sessions() as session:
                material = load_material(session, start["run_id"])
            before = service.bundle_for(material.job_id)
            reproduced = asyncio.run(service.reproduce(job_id=material.job_id))
            assert before.output_hash == reproduced.output_hash
            diffs = {}
            for name in ("return", "drawdown", "pe", "pb"):
                left = next(v for v in before.values if v.name == name)
                right = next(v for v in reproduced.values if v.name == name)
                assert left.value is not None and right.value is not None
                diff = abs(left.value - right.value)
                relative = diff / abs(left.value) if left.value else diff
                assert (relative if name in {"pe", "pb"} else diff) <= (
                    service.input_for(material.job_id).spec.relative_tolerance
                    if name in {"pe", "pb"}
                    else service.input_for(material.job_id).spec.absolute_tolerance
                )
                diffs[name] = {"absolute": str(diff), "relative": str(relative)}
            report = client.get("/api/reports/" + detail["report_id"])
            assert report.status_code == 200, report.text
            citations = client.get("/api/reports/" + detail["report_id"] + "/citations").json()
            assert len(citations) == detail["citation_count"] > 0
            assert client.get("/api/citations/" + citations[0]["citation_id"]).status_code == 200
            export = client.get("/api/reports/" + detail["report_id"] + "/export?format=markdown")
            assert export.status_code == 200, export.text
            for name, content in (
                (f"run-{ordinal}.json", detail),
                (f"report-{ordinal}.json", report.json()),
                (f"citations-{ordinal}.json", citations),
                (f"request-{ordinal}.json", payload),
            ):
                (output / name).write_text(
                    json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            (output / f"report-{ordinal}.md").write_bytes(export.content)
            (output / f"artifact-{ordinal}.json").write_text(
                before.model_dump_json(indent=2), encoding="utf-8"
            )
            results.append(
                dict(
                    **start,
                    report_id=detail["report_id"],
                    instrument_id=instrument_id,
                    charts=len(detail["charts"]),
                    evidence_count=detail["evidence_count"],
                    citation_count=detail["citation_count"],
                    output_hash=before.output_hash,
                    same_environment_bytes=True,
                    differences=diffs,
                    completeness=detail["completeness"],
                    sample_count=next(v.sample_count for v in before.values if v.name == "return"),
                    sections=[
                        dict(type=s["section_type"], units=len(s["content"]["units"]))
                        for s in report.json()["sections"]
                    ],
                    independent_values=[
                        v.model_dump(mode="json")
                        for v in before.values
                        if v.name in {"pe", "pb", "roe", "net_profit_growth", "revenue_growth"}
                    ],
                )
            )
            print(
                f"Completed real frozen HTTP run {ordinal}: {len(detail['charts'])} exhibits",
                flush=True,
            )
    (output / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(".phase3-quant-n/financial-frozen-02"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.source, args.output)
