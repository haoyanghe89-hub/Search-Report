from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.repositories import InvestigationRepository


@pytest.fixture
def investigation_store(
    tmp_path: Path,
) -> Iterator[tuple[InvestigationRepository, Engine, str]]:
    root = Path(__file__).resolve().parents[3]
    url = f"sqlite:///{(tmp_path / 'investigation.db').as_posix()}"
    config = Config(root / "alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_investigation_engine(url)
    try:
        yield InvestigationRepository(create_session_factory(engine)), engine, url
    finally:
        engine.dispose()


@pytest.fixture
def unfinished_legacy_runs(monkeypatch):
    """Exercise pre-J unfinished checkpoints, not J's completed report terminal.

    Recovery tests intentionally simulate a crash *before* the new local finalizer
    can commit. Default finalization is covered by test_taskj_delivery. There is
    no production setting that disables graceful finalization.
    """
    from marketpulse.investigation.domain.enums import ReportType, RunStatus
    from marketpulse.investigation.domain.runtime import InvestigationRun
    from marketpulse.investigation.live_runtime import LiveInvestigationService

    schedule = LiveInvestigationService._schedule

    def schedule_unfinished(self, run_id, authorized=frozenset(), *, finalize_only=False):
        if not finalize_only:
            schedule(self, run_id, authorized)

    async def before_finalizer(self, run_id, reason):
        run = self.repository.get(InvestigationRun, run_id)
        if reason and reason.startswith("USER_CANCELLED"):
            status = RunStatus.CANCELLED
            reason = "USER_CANCELLED"
        elif reason and (reason.startswith("SERVER_") or reason.startswith("WATCHDOG_")):
            status = RunStatus.INTERRUPTED
        elif run.status in {RunStatus.BLOCKED, RunStatus.READY_FOR_REPORT}:
            status = run.status
        else:
            status = RunStatus.FAILED
        self._finish(run_id, status, reason)
        try:
            await self._report(run_id, ReportType.INVESTIGATION_STATUS)
        except Exception:
            self._finish(run_id, RunStatus.FAILED, "ConnectionError: report not finalized")

    monkeypatch.setattr(LiveInvestigationService, "_schedule", schedule_unfinished)
    monkeypatch.setattr(LiveInvestigationService, "_finalize_run", before_finalizer)
