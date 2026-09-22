"""Generate the committed East Palestine delivery artifacts from a real Replay run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import select

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.investigation.case_replay import (
    OFFICIAL_SOURCES,
    RECORDING_RUN_ID,
    SECONDARY_SOURCES,
    EastPalestineReplayService,
)
from marketpulse.investigation.domain.reports import Report
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.feedback.trace import TraceResolver
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import (
    CallBindingRow,
    CitationRow,
    RecordedModelCallRow,
    RecordedToolCallRow,
    ReportSectionRow,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.reporting.models import Citation
from marketpulse.investigation.reporting.persistence import ReportGovernanceRepository
from marketpulse.investigation.reporting.renderer import render_markdown
from marketpulse.investigation.reporting.writer import (
    ContentClass,
    DraftSection,
    NarrativeUnit,
    ReportDraft,
    SectionStatus,
)
from marketpulse.investigation.server import _upgrade_database

ROOT = Path(__file__).resolve().parents[1]
CASE_ROOT = ROOT / "case_data" / "east_palestine_2023"
OUTPUT_ROOT = CASE_ROOT / "outputs"
CLEANED_ROOT = CASE_ROOT / "cleaned"


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _row(row: Any) -> dict[str, Any]:
    mapper = sqlalchemy_inspect(type(row))
    return {
        attribute.columns[0].name: getattr(row, attribute.key) for attribute in mapper.column_attrs
    }


def _domain(items: tuple[Any, ...] | list[Any]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


def _draft(session: Any, report: Report) -> ReportDraft:
    rows = session.scalars(
        select(ReportSectionRow)
        .where(ReportSectionRow.report_id == report.report_id)
        .order_by(ReportSectionRow.order_index)
    ).all()
    sections = []
    for row in rows:
        content = dict(row.structured_content or {})
        section_key = str(row.section_type)
        units = tuple(
            NarrativeUnit(
                unit_key=unit["unit_key"],
                section_key=section_key,
                text=unit["text"],
                content_class=ContentClass(unit["content_class"]),
                claim_refs=tuple(unit.get("claim_refs", [])),
            )
            for unit in content.get("units", [])
        )
        sections.append(
            DraftSection(
                section_key=section_key,
                status=SectionStatus(content["status"]),
                units=units,
            )
        )
    return ReportDraft(report_type=report.report_type, sections=tuple(sections))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _run() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    CLEANED_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="marketpulse-east-palestine-", ignore_cleanup_errors=True
    ) as temp:
        runtime_root = Path(temp)
        database_url = f"sqlite:///{(runtime_root / 'delivery.db').as_posix()}"
        _upgrade_database(database_url)
        engine = create_investigation_engine(database_url)
        sessions = create_session_factory(engine)
        repository = InvestigationRepository(sessions)
        blob_root = runtime_root / "blobs"
        blobs = LocalContentAddressedBlobStorage(blob_root)
        service = EastPalestineReplayService(
            sessions=sessions,
            repository=repository,
            case_root=CASE_ROOT,
            blob_root=blob_root,
        )
        outcome = await service.run()
        state = FeedbackStore(sessions, repository).state(outcome.run_id)
        report = repository.get(Report, outcome.report_id or "")

        with sessions() as session:
            citation_rows = session.scalars(
                select(CitationRow)
                .where(CitationRow.report_id == report.report_id)
                .order_by(CitationRow.display_ordinal)
            ).all()
            citations = [repository.get(Citation, row.citation_id) for row in citation_rows]
            draft = _draft(session, report)
            bindings = session.scalars(
                select(CallBindingRow)
                .where(CallBindingRow.run_id == outcome.run_id)
                .order_by(CallBindingRow.logical_step_key, CallBindingRow.call_ordinal)
            ).all()
            recorded_ids = {binding.recorded_call_id for binding in bindings}
            model_calls = session.scalars(
                select(RecordedModelCallRow)
                .where(RecordedModelCallRow.call_id.in_(recorded_ids))
                .order_by(RecordedModelCallRow.call_id)
            ).all()
            tool_calls = session.scalars(
                select(RecordedToolCallRow)
                .where(RecordedToolCallRow.call_id.in_(recorded_ids))
                .order_by(RecordedToolCallRow.call_id)
            ).all()
            governance = ReportGovernanceRepository(sessions)
            evaluation = governance.latest_evaluation_in_session(session, report.report_id)
            findings = governance.findings_for_report_in_session(session, report.report_id)
            request = governance.pending_request_for_report_in_session(
                session, report.report_id, datetime.now(UTC)
            )
            snapshot = governance.latest_snapshot_for_run_in_session(session, outcome.run_id)

        report_path = OUTPUT_ROOT / "east-palestine-full-investigation-report.md"
        report_path.write_text(render_markdown(draft, citations), encoding="utf-8")

        fixture_by_url = {
            item.url.rstrip("/"): item for item in (*SECONDARY_SOURCES, *OFFICIAL_SOURCES)
        }
        snapshots_by_source = {item.source_id: item for item in state.snapshots}
        artifacts_by_snapshot: dict[str, list[Any]] = {}
        for artifact in state.artifacts:
            artifacts_by_snapshot.setdefault(artifact.snapshot_id, []).append(artifact)
        source_metadata = []
        for source in sorted(state.sources, key=lambda item: str(item.canonical_url)):
            snapshot_item = snapshots_by_source[source.source_id]
            fixture = fixture_by_url[str(source.canonical_url).rstrip("/")]
            saved_path = (CASE_ROOT / "snapshots" / fixture.filename).resolve()
            cleaned_path = CLEANED_ROOT / f"{Path(fixture.filename).stem}.txt"
            if snapshot_item.cleaned_blob_ref is None:
                raise RuntimeError(f"source {source.source_id} has no cleaned content")
            cleaned_path.write_bytes(blobs.get_bytes(snapshot_item.cleaned_blob_ref))
            source_metadata.append(
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "canonical_url": str(source.canonical_url),
                    "publisher": source.publisher,
                    "source_type": source.source_type.value,
                    "is_official": source.is_official,
                    "is_first_hand": source.is_first_hand,
                    "saved_snapshot_path": saved_path.relative_to(ROOT).as_posix(),
                    "saved_snapshot_sha256": _sha256(saved_path),
                    "saved_snapshot_bytes": saved_path.stat().st_size,
                    "cleaned_content_path": cleaned_path.relative_to(ROOT).as_posix(),
                    "cleaned_content_sha256": _sha256(cleaned_path),
                    "snapshot_id": snapshot_item.snapshot_id,
                    "snapshot_raw_sha256": snapshot_item.raw_sha256,
                    "snapshot_cleaned_sha256": snapshot_item.cleaned_sha256,
                    "parser_name": snapshot_item.parser_name,
                    "parser_version": snapshot_item.parser_version,
                    "artifact_content_hashes": sorted(
                        artifact.sha256
                        for artifact in artifacts_by_snapshot.get(snapshot_item.snapshot_id, [])
                    ),
                }
            )

        source_metadata_path = CASE_ROOT / "source-metadata.json"
        _write_json(source_metadata_path, source_metadata)

        trace_resolver = TraceResolver(sessions)
        claim_traces = [
            trace_resolver.claim(claim.claim_id).model_dump(mode="json") for claim in state.claims
        ]
        trace_payload: dict[str, Any] = {
            "trace_schema_version": "east-palestine-delivery-trace-v1",
            "generated_at": datetime.now(UTC),
            "case_id": outcome.case_id,
            "investigation_id": outcome.investigation_id,
            "recording_source_run_id": RECORDING_RUN_ID,
            "replay_run_id": outcome.run_id,
            "run": state.run.model_dump(mode="json"),
            "budget": state.budget.model_dump(mode="json"),
            "agent_steps": _domain(list(state.steps)),
            "call_bindings": [_row(row) for row in bindings],
            "recorded_model_calls": [_row(row) for row in model_calls],
            "recorded_tool_calls": [_row(row) for row in tool_calls],
            "research_tasks": _domain(list(state.tasks)),
            "sources": _domain(list(state.sources)),
            "source_snapshots": _domain(list(state.snapshots)),
            "document_artifacts": _domain(list(state.artifacts)),
            "evidence": _domain(list(state.evidence)),
            "claims": _domain(list(state.claims)),
            "claim_evidence_relations": _domain(list(state.relations)),
            "validation_results": _domain(list(state.validations)),
            "conflicts": _domain(list(state.conflicts)),
            "research_gaps": _domain(list(state.gaps)),
            "timeline_events": _domain(list(state.timeline_events)),
            "claim_trace_paths": claim_traces,
            "report_input_snapshot": (
                snapshot.model_dump(mode="json") if snapshot is not None else None
            ),
            "report": report.model_dump(mode="json"),
            "citations": _domain(citations),
            "report_validation_findings": _domain(findings),
            "release_policy_evaluation": (
                evaluation.model_dump(mode="json") if evaluation is not None else None
            ),
            "review_request": request.model_dump(mode="json") if request is not None else None,
            "report_artifact": {
                "path": report_path.relative_to(ROOT).as_posix(),
                "sha256": _sha256(report_path),
            },
        }
        canonical_trace = json.dumps(
            trace_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
        trace_payload["trace_hash"] = hashlib.sha256(canonical_trace.encode()).hexdigest()
        trace_path = OUTPUT_ROOT / "east-palestine-run-trace.json"
        _write_json(trace_path, trace_payload)

        report_metadata = {
            "generated_by": "ReportPipeline + DeterministicWriter + CitationFactory",
            "report": report.model_dump(mode="json"),
            "release_policy_evaluation": (
                evaluation.model_dump(mode="json") if evaluation is not None else None
            ),
            "review_request": request.model_dump(mode="json") if request is not None else None,
            "citation_count": len(citations),
            "section_count": len(draft.sections),
            "report_markdown_path": report_path.relative_to(ROOT).as_posix(),
            "report_markdown_sha256": _sha256(report_path),
            "trace_path": trace_path.relative_to(ROOT).as_posix(),
            "trace_sha256": _sha256(trace_path),
        }
        _write_json(OUTPUT_ROOT / "east-palestine-report-metadata.json", report_metadata)

        manifest = {
            "case_id": "east_palestine_2023",
            "case_version": "1.0.0-phase5-replay",
            "status": "replay_ready",
            "workflow_version": state.run.workflow_version,
            "schema_version": "phase5-report-governance-v1",
            "recorded_source_run_id": RECORDING_RUN_ID,
            "recorded_counts": {
                "sources": len(state.sources),
                "snapshots": len(state.snapshots),
                "artifacts": len(state.artifacts),
                "evidence": len(state.evidence),
                "claims": len(state.claims),
                "validations": len(state.validations),
                "model_calls": len(model_calls),
                "tool_calls": len(tool_calls),
            },
            "source_metadata_path": source_metadata_path.relative_to(ROOT).as_posix(),
            "sources": source_metadata,
            "delivery_artifacts": {
                "structured_trace": trace_path.relative_to(ROOT).as_posix(),
                "report_markdown": report_path.relative_to(ROOT).as_posix(),
                "report_metadata": (OUTPUT_ROOT / "east-palestine-report-metadata.json")
                .relative_to(ROOT)
                .as_posix(),
            },
            "last_generated_result": {
                "run_status": outcome.run_status,
                "report_type": report.report_type.value,
                "release_status": outcome.release_status,
                "hard_finding_count": len(
                    [finding for finding in findings if finding.severity.value == "HARD"]
                ),
            },
            "notes": (
                "The report, trace, cleaned content, and metadata are generated from the full "
                "recording-source plus isolated Replay pipeline. Expected conclusions are not "
                "used as execution input."
            ),
        }
        _write_json(CASE_ROOT / "manifest.json", manifest)
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
