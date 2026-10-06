"""Offline diagnostic/recovery of the single authorized Task J quick run.

No provider calls: only persisted materials and deterministic report writer.
"""

import argparse
import asyncio
import json
import logging
import traceback
from pathlib import Path

from sqlalchemy import select

from marketpulse.config import Settings
from marketpulse.investigation.domain.enums import ReportType
from marketpulse.investigation.domain.runtime import InvestigationRun
from marketpulse.investigation.live_runtime import LiveInvestigationService
from marketpulse.investigation.persistence.base import (
    create_investigation_engine,
    create_session_factory,
)
from marketpulse.investigation.persistence.models import ReportRow, ReportSectionRow
from marketpulse.investigation.persistence.repositories import InvestigationRepository


def export_reports(sessions, directory, run_id):
    with sessions() as session:
        reports = session.scalars(
            select(ReportRow).where(ReportRow.run_id == run_id).order_by(ReportRow.version)
        ).all()
        for report in reports:
            sections = session.scalars(
                select(ReportSectionRow)
                .where(ReportSectionRow.report_id == report.report_id)
                .order_by(ReportSectionRow.order_index)
            ).all()
            content = [f"# {report.report_id} / {report.report_type.value}"]
            for section in sections:
                content.append(f"\n## {section.section_type}\n")
                content.extend(
                    unit["text"] + "\n"
                    for unit in (section.structured_content or {}).get("units", [])
                )
            (directory / f"{report.report_id}.md").write_text("\n".join(content), encoding="utf-8")


async def main(directory: Path):
    data = json.loads((directory / "final.json").read_text(encoding="utf-8"))
    run_id = data["run_id"]
    engine = create_investigation_engine(f"sqlite:///{(directory / 'live.db').as_posix()}")
    sessions = create_session_factory(engine)
    repository = InvestigationRepository(sessions)
    service = LiveInvestigationService(
        sessions=sessions, repository=repository, settings=Settings(), blob_root=directory / "blobs"
    )
    try:
        if repository.get(InvestigationRun, run_id).status.value == "COMPLETED":
            export_reports(sessions, directory, run_id)
            print("Already completed; no duplicate report or provider call.")
            return
        try:
            await service._report(run_id, ReportType.INVESTIGATION_STATUS)
        except Exception:
            diagnostic = traceback.format_exc()
            (directory / "report-diagnostic.txt").write_text(diagnostic, encoding="utf-8")
            print(diagnostic)
        await service._finalize_run(
            run_id,
            "RUN_TIMEOUT：快速档研究已到时限；现有归档材料已用于报告收尾。"
            "若需确认更多发现，请选择更长档位并补充独立一手材料。",
        )
        run = repository.get(InvestigationRun, run_id).model_dump(mode="json")
        (directory / "offline-recovery.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        export_reports(sessions, directory, run_id)
        print(json.dumps(run, ensure_ascii=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(args.directory.resolve()))
