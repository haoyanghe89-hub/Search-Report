"""One explicitly authorized LIVE check in an isolated database, with durable progress."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from unittest.mock import patch

from pydantic import SecretStr
from sqlalchemy import create_engine, select

from marketpulse.config import Settings
from marketpulse.investigation.adapters.model import OpenAICompatibleModelAdapter
from marketpulse.investigation.domain.runtime import Investigation, InvestigationRun
from marketpulse.investigation.feedback.store import FeedbackStore
from marketpulse.investigation.live_runtime import LiveInvestigationService
from marketpulse.investigation.persistence.base import (
    Base,
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import ReportProjectionRow, ReportRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository
from marketpulse.investigation.recovery import ResumeRequest, live_feedback_config


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def resume_request(info: dict, authorized_ids: list[str]) -> ResumeRequest:
    """Fail closed if the explicit consent no longer matches the unknown calls."""
    if not info["can_resume"]:
        raise ValueError(f"run is not resumable: {info['reason']}")
    actual = {call["intent_id"] for call in info["unknown_calls"]}
    if set(authorized_ids) != actual or len(authorized_ids) != len(actual):
        raise ValueError("explicit retry consent must match the unknown intent IDs exactly")
    return ResumeRequest(
        expected_state_version=info["state_version"],
        retry_unknown_intent_ids=authorized_ids,
    )


def create_new(args: argparse.Namespace):
    # Existing investigation data is read-only. Never recover/restart existing runs.
    source_engine = create_engine(
        f"sqlite:///file:{Path(args.database).as_posix()}?mode=ro&uri=true"
    )
    source_repository = InvestigationRepository(create_session_factory(source_engine))
    with sqlite3.connect(f"file:{Path(args.database).as_posix()}?mode=ro", uri=True) as db:
        found = db.execute(
            "SELECT investigation_id FROM inv_runs WHERE run_id=?", (args.origin_run,)
        ).fetchone()
    if found is None:
        raise ValueError("origin run not found")
    investigation = source_repository.get(Investigation, found[0])
    source_engine.dispose()
    target = args.output
    # Fail closed on an existing result directory: never accidentally run twice.
    target.mkdir(parents=True, exist_ok=False)
    database = target / "live.db"
    settings = Settings.from_env().model_copy(
        update={"database_url": SecretStr(f"sqlite:///{database.as_posix()}")}
    )
    engine = create_investigation_engine(settings.database_url.get_secret_value())
    Base.metadata.create_all(engine)
    sessions = create_session_factory(engine)
    repository = InvestigationRepository(sessions)
    repository.add(investigation)
    service = LiveInvestigationService(
        sessions=sessions,
        repository=repository,
        settings=settings,
        blob_root=target / "blobs",
    )
    save(
        target / "configuration.json",
        {
            "origin_run": args.origin_run,
            "investigation": investigation.model_dump(mode="json"),
            "feedback": live_feedback_config(settings).model_dump(mode="json"),
            "max_tokens": settings.max_tokens,
            "max_model_calls": settings.max_model_calls,
            "model": settings.model,
            "model_thinking_enabled": settings.model_thinking_enabled,
            "reasoning_model": settings.reasoning_model,
            "model_force_single": settings.model_force_single,
            "reasoning_effort": settings.reasoning_effort,
            "reasoning_output_tokens": settings.reasoning_output_tokens,
            "model_retry_attempts": settings.model_retry_attempts,
            "model_auto_retry": settings.model_auto_retry,
            "model_connect_timeout_seconds": settings.model_connect_timeout_seconds,
            "model_read_timeout_seconds": settings.model_read_timeout_seconds,
            "allow_proxy_dns": settings.allow_proxy_dns,
            "timeout_seconds": settings.total_timeout_seconds,
        },
    )
    run_id = (
        service.start(investigation.investigation_id, depth=args.depth)
        if args.depth
        else service.start(investigation.investigation_id)
    )
    return engine, sessions, repository, service, run_id


def resume_existing(args: argparse.Namespace):
    database = Path(args.database).resolve(strict=True)
    workspace = Path(__file__).resolve().parents[1]
    allowed = (workspace / "reports/taskd", workspace / "reports/taski")
    if not database.is_file() or not any(database.is_relative_to(p) for p in allowed):
        raise ValueError("resume is restricted to an existing isolated task D/I database")
    blobs = database.parent / "blobs"
    if not blobs.is_dir():
        raise ValueError("existing blob archive is required")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = Settings.from_env().model_copy(
        update={"database_url": SecretStr(f"sqlite:///{database.as_posix()}")}
    )
    engine = create_investigation_engine(settings.database_url.get_secret_value())
    sessions = create_session_factory(engine)
    repository = InvestigationRepository(sessions)
    service = LiveInvestigationService(
        sessions=sessions, repository=repository, settings=settings, blob_root=blobs
    )
    if args.recover_interrupted:
        with sqlite3.connect(database) as db:
            runs = db.execute("SELECT run_id FROM inv_runs").fetchall()
        if runs != [(args.resume_run,)]:
            raise ValueError("restart recovery requires an isolated single-run database")
        service.recover_interrupted()
    info = service.recovery.inspect(args.resume_run)
    if args.retry_unknown_outcomes:
        args.retry_unknown_intent = [c["intent_id"] for c in info["unknown_calls"]]
    save(args.output / "recovery-before.json", info)
    request = resume_request(info, args.retry_unknown_intent)
    save(
        args.output / "authorization.json",
        {
            "at": datetime.now(UTC).isoformat(),
            "run_id": args.resume_run,
            "resume_request": request.model_dump(mode="json"),
            "possible_duplicate_provider_charges": True,
            "consent": "explicit user confirmation; only the listed unknown calls",
        },
    )
    service.resume(args.resume_run, request)
    return engine, sessions, repository, service, args.resume_run


async def run(args: argparse.Namespace) -> None:
    if not args.resume_run and args.retry_unknown_intent:
        raise ValueError("retry consent requires --resume-run")
    engine, sessions, repository, service, run_id = (
        resume_existing(args) if args.resume_run else create_new(args)
    )
    target = args.output
    task = service.tasks[run_id]
    feedback = FeedbackStore(sessions, repository)
    sequence = 0
    while True:
        state = feedback.state(run_id)
        snapshot = {
            "at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "phase": state.run.current_phase.value,
            "status": state.run.status.value,
            "budget": state.budget.model_dump(mode="json"),
            "sources": len(state.sources),
            "snapshots": len(state.snapshots),
            "evidence": len(state.evidence),
            "claims": len(state.claims),
            "validation_statuses": dict(Counter(c.validation_status.value for c in state.claims)),
            "gaps": len(state.gaps),
        }
        save(target / f"progress-{sequence:04d}.json", snapshot)
        save(target / "progress.json", snapshot)
        print(json.dumps(snapshot, ensure_ascii=True), flush=True)
        sequence += 1
        if task.done():
            await task
            break
        await asyncio.wait({task}, timeout=20)
    with sessions() as session:
        reports = session.scalars(select(ReportRow).where(ReportRow.run_id == run_id)).all()
        snapshot["reports"] = [
            {
                "report_id": r.report_id,
                "report_type": r.report_type.value,
                "release_status": (
                    session.get(ReportProjectionRow, r.report_id).release_status.value
                ),
            }
            for r in reports
        ]
    snapshot["run"] = repository.get(InvestigationRun, run_id).model_dump(mode="json")
    save(target / "final.json", snapshot)
    engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-run", default="RUN-LIVE-c455bfabb21d43d4")
    parser.add_argument("--depth", choices=("quick", "standard", "deep"))
    parser.add_argument("--database", default="data/blackboard.db")
    parser.add_argument("--resume-run")
    parser.add_argument("--retry-unknown-intent", action="append", default=[])
    parser.add_argument(
        "--retry-unknown-outcomes",
        action="store_true",
        help="Explicit task I readonly retry consent; possible duplicate model charge",
    )
    parser.add_argument(
        "--recover-interrupted",
        action="store_true",
        help="Only after terminating the owner of an isolated single-run database",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--capture-analysis-output", action="store_true")
    args = parser.parse_args()
    args.output = Path(args.output).resolve()
    # Avoid HTTP client/provider logs containing request URLs/headers or prompt content.
    logging.basicConfig(level=logging.CRITICAL)
    with ExitStack() as stack:
        if args.capture_analysis_output:
            sequence = [0]

            def capture(request, content):
                if request.prompt_version.endswith(":analyst.analyze"):
                    sequence[0] += 1
                    # Explicitly requested diagnostic output, no keys/headers/provider prompts.
                    save(
                        args.output / f"analysis-raw-{sequence[0]:04d}.json",
                        {"prompt_version": request.prompt_version, "raw_content": content},
                    )

            stack.enter_context(
                patch(
                    "marketpulse.investigation.live_runtime.OpenAICompatibleModelAdapter",
                    partial(OpenAICompatibleModelAdapter, response_observer=capture),
                )
            )
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
