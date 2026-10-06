"""Offline Task N verification using an isolated copy of M's real frozen data."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.domain.enums import ReportType, RunMode, RunStatus, WorkflowPhase
from marketpulse.investigation.domain.runtime import (
    Investigation,
    InvestigationRun,
    InvestigationScope,
)
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.pipeline import ReportPipeline
from marketpulse.investigation.reporting.renderer import render_json
from marketpulse.investigation.reporting.writer import DeterministicWriter
from marketpulse.quant.domain import MetricSpec
from marketpulse.quant.evidence import build_computation_evidence
from marketpulse.quant.execution.service import QuantService
from marketpulse.quant.reporting import build_material, persist_material
from marketpulse.quant.storage.models import DatasetSnapshotRow, InstrumentRow
from marketpulse.quant.storage.snapshots import SnapshotStore
from marketpulse.quant.validation import verify_cell


async def verify(destination, source):
    root = Path.cwd().resolve()
    source = source.resolve()
    if source != root / ".phase3-quant-m/live-04" and not source.is_relative_to(
        root / ".phase3-quant-n"
    ):
        raise ValueError("only private frozen task bundles accepted")
    target = destination.resolve()
    if not target.is_relative_to(root / ".phase3-quant-n") or target.exists():
        raise ValueError("fresh task-specific destination required")
    target.mkdir(parents=True)
    with sqlite3.connect(f"file:{source / 'metadata.sqlite'}?mode=ro", uri=True) as src:
        with sqlite3.connect(target / "metadata.sqlite") as dst:
            src.backup(dst)
    shutil.copytree(source / "blobs", target / "blobs")
    url = "sqlite:///" + (target / "metadata.sqlite").as_posix()
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_investigation_engine(url)
    sessions = create_session_factory(engine)
    store = SnapshotStore(sessions, LocalContentAddressedBlobStorage(target / "blobs"))
    service = QuantService(store, root=root)
    repository = InvestigationRepository(sessions)

    # Event loop has already created its Windows self-pipe. All subsequent
    # external connections are forbidden; the compute child denies sockets too.
    def denied(*args, **kwargs):
        raise AssertionError("offline acceptance forbids network")

    socket.socket.connect = denied
    socket.create_connection = denied
    with sessions() as session:
        instruments = list(session.scalars(select(InstrumentRow.instrument_id)))
        snapshots = [store.load(i) for i in session.scalars(select(DatasetSnapshotRow.snapshot_id))]
    results = []
    for ordinal, instrument_id in enumerate(instruments):
        selected = [
            s
            for s in snapshots
            if instrument_id in s.result.request.instruments
            and (s.result.request.dataset != "daily" or s.result.request.adjustment == "raw")
        ]
        financial = [s for s in selected if s.result.request.normalizer_version == "3-parent-2"]
        if financial:
            selected = [
                s
                for s in selected
                if s.result.request.dataset not in {"financial", "valuation", "calendar"}
            ]
            selected.extend(financial)
            selected.append(
                next(
                    s
                    for s in snapshots
                    if instrument_id in s.result.request.instruments
                    and s.result.request.dataset == "calendar"
                    and s.result.request.start.year == 2022
                )
            )
        now = datetime.now(UTC)
        investigation_id, run_id = f"N-QI-{ordinal}", f"N-QR-{ordinal}"
        repository.add(
            Investigation(
                investigation_id=investigation_id,
                title="冻结单标的投研验证",
                event_description="Task M archived market data; offline Task N computation",
                investigation_goal="核对历史表现与估值所需材料，不生成买卖建议",
                scope=InvestigationScope(summary="单标的冻结窗口"),
                created_at=now,
                updated_at=now,
            )
        )
        repository.add(
            InvestigationRun(
                run_id=run_id,
                investigation_id=investigation_id,
                mode=RunMode.LIVE,
                status=RunStatus.READY_FOR_REPORT,
                current_phase=WorkflowPhase.REPORT,
                checkpoint_version=1,
                state_version=1,
                workflow_version="quant-v1",
                created_at=now,
                updated_at=now,
            )
        )
        for snapshot in selected:
            store.attach(snapshot.snapshot_id, investigation_id)
        asof = next(s.result.request.asof for s in selected if s.result.request.dataset == "daily")
        job_id = await service.submit(
            run_id=run_id,
            spec=MetricSpec(),
            inputs=tuple(s.snapshot_id for s in selected),
            instrument_id=instrument_id,
            asof=asof,
            idempotency_key="frozen-metrics",
        )
        bundle = service.bundle_for(job_id)
        again = await service.reproduce(job_id=job_id)
        assert bundle.output_hash == again.output_hash
        differences = {}
        for name in ("return", "drawdown", "pe", "pb"):
            left = next(v for v in bundle.values if v.name == name)
            right = next(v for v in again.values if v.name == name)
            if left.value is None or right.value is None:
                differences[name] = {"missing": left.missing_reason}
                continue
            difference = abs(left.value - right.value)
            relative = difference / abs(left.value) if left.value else difference
            assert (relative if name in {"pe", "pb"} else difference) <= (
                service.input_for(job_id).spec.relative_tolerance
                if name in {"pe", "pb"}
                else service.input_for(job_id).spec.absolute_tolerance
            )
            differences[name] = {"absolute": str(difference), "relative": str(relative)}
        index = next(i for i, v in enumerate(bundle.values) if v.name == "return")
        evidence = build_computation_evidence(bundle, metric_path=f"/values/{index}")
        rejected = False
        try:
            verify_cell(bundle, evidence.model_copy(update={"unit": "percent"}))
        except ValueError:
            rejected = True
        assert rejected
        material = await build_material(service, job_id=job_id)
        persist_material(sessions, run_id=run_id, material=material)
        report = await ReportPipeline(
            sessions, repository, DeterministicWriter(), quant_service=service
        ).generate(
            run_id=run_id, report_type=ReportType.INVESTIGATION_STATUS, now=datetime.now(UTC)
        )
        assert report.hard_finding_count == 0, report.findings
        report_path = target / f"report-{ordinal}.md"
        report_path.write_text(report.markdown, encoding="utf-8")
        (target / f"report-{ordinal}.json").write_text(
            json.dumps(
                render_json(report.draft, list(report.citations)), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        (target / f"citations-{ordinal}.json").write_text(
            json.dumps(
                [c.model_dump(mode="json") for c in report.citations],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (target / f"artifact-{ordinal}.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )
        results.append(
            {
                "instrument_id": instrument_id,
                "job_id": job_id,
                "artifact_id": bundle.artifact_id,
                "manifest_hash": bundle.manifest_hash,
                "output_hash": bundle.output_hash,
                "same_environment_bytes": True,
                "numeric_reproduction_differences": differences,
                "tamper_rejected": True,
                "sample_count": next(v.sample_count for v in bundle.values if v.name == "return"),
                "scalar_values": [
                    v.model_dump(mode="json") for v in bundle.values if not v.row_keys
                ],
                "statuses": {
                    s: sum(c.validation.status == s for c in material.claims)
                    for s in ("VERIFIED", "PROBABLE", "UNVERIFIED")
                },
                "completeness": material.completeness,
                "report": str(report_path),
                "sections": [
                    {"key": s.section_key, "units": len(s.units)} for s in report.draft.sections
                ],
                "citations": len(report.citations),
                "limitations": material.limitations,
            }
        )
    (target / "summary.json").write_text(
        json.dumps(
            {"offline": True, "source_bundle": str(source), "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    engine.dispose()
    print(json.dumps({"output": str(target), "instruments": len(results), "offline": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=Path(".phase3-quant-m/live-04"))
    args = parser.parse_args()
    asyncio.run(verify(args.output, args.source))
