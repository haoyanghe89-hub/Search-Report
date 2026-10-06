"""Explicit archive deletion with transaction-scoped ownership and shared blob GC."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping

from sqlalchemy import and_, delete, or_, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.infrastructure.storage.local import LocalContentAddressedBlobStorage
from marketpulse.infrastructure.storage.models import BlobRef
from marketpulse.investigation.domain.enums import RunStatus
from marketpulse.investigation.persistence.base import Base
from marketpulse.investigation.persistence.models import (
    ClaimRow,
    DeletionPermitRow,
    InvestigationRow,
    InvestigationRunRow,
    RecordedHumanReviewDecisionRow,
    ReportRow,
)

ACTIVE = {
    RunStatus.CREATED,
    RunStatus.PENDING,
    RunStatus.WAITING_FOR_EXECUTION,
    RunStatus.RUNNING,
    RunStatus.VERIFYING,
}
REF_PATTERN = re.compile(r"blob://sha256/[0-9a-f]{64}")
LOG = logging.getLogger(__name__)


class ActiveInvestigationError(ValueError):
    pass


def _refs(value: object) -> set[str]:
    if isinstance(value, str):
        return set(REF_PATTERN.findall(value))
    if isinstance(value, Mapping):
        return set().union(*(_refs(v) for v in value.values()))
    if isinstance(value, (tuple, list)):
        return set().union(*(_refs(v) for v in value))
    return set()


def _lock(session: Session) -> None:
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))


def delete_archive(
    sessions: sessionmaker[Session],
    investigation_id: str,
    blobs: LocalContentAddressedBlobStorage | None = None,
) -> dict:
    """Own rows only. Cross-archive references must restrict or SET NULL, never cascade."""
    candidates: set[str] = set()
    counts = {}
    with sessions.begin() as session:
        _lock(session)
        investigation = session.scalar(
            select(InvestigationRow)
            .where(InvestigationRow.investigation_id == investigation_id)
            .with_for_update()
        )
        if investigation is None:
            return {"investigation_id": investigation_id, "deleted": False, "already_deleted": True}
        runs = session.scalars(
            select(InvestigationRunRow).where(
                InvestigationRunRow.investigation_id == investigation_id
            )
        ).all()
        if any(
            r.status in ACTIVE
            or r.owner_instance_id is not None
            or (r.current_phase.value == "REPORT" and r.completed_at is None)
            for r in runs
        ):
            raise ActiveInvestigationError(
                "调查仍在运行或报告收尾中，请先停止并等待收尾完成后删除。"
            )
        run_ids = [r.run_id for r in runs]
        tables = {
            name: table
            for name, table in Base.metadata.tables.items()
            if name.startswith("inv_") and name != "inv_deletion_permits"
        }
        selected = {}
        # All directly owned rows first; auxiliary tables are selected only by FK.
        for name, table in tables.items():
            conditions = []
            if "investigation_id" in table.c:
                conditions.append(table.c.investigation_id == investigation_id)
            if "run_id" in table.c:
                conditions.append(table.c.run_id.in_(run_ids))
            selected[name] = (
                list(session.execute(select(table).where(or_(*conditions))).mappings())
                if conditions
                else []
            )
        changed = True
        while changed:
            changed = False
            for name, table in tables.items():
                if "investigation_id" in table.c or "run_id" in table.c:
                    continue  # Never follow provenance into another owned archive.
                conditions = []
                for fk in table.foreign_keys:
                    parent_rows = selected.get(fk.column.table.name, [])
                    ids = {r[fk.column.name] for r in parent_rows}
                    if ids:
                        conditions.append(fk.parent.in_(ids))
                if conditions:
                    rows = list(session.execute(select(table).where(or_(*conditions))).mappings())
                    if len(rows) != len(selected[name]):
                        selected[name] = rows
                        changed = True
        # Recorded reviews have semantic hashes, not ownership FKs. Delete only
        # reviews exclusively belonging to this archive; shared hashes survive.
        hashes = {r["report_hash"] for r in selected.get("inv_reports", [])}
        shared_hashes = set(
            session.scalars(
                select(ReportRow.report_hash).where(
                    ReportRow.investigation_id != investigation_id,
                    ReportRow.report_hash.in_(hashes),
                )
            )
        )
        selected[RecordedHumanReviewDecisionRow.__tablename__] = list(
            session.execute(
                select(RecordedHumanReviewDecisionRow.__table__).where(
                    RecordedHumanReviewDecisionRow.report_hash.in_(hashes - shared_hashes)
                )
            ).mappings()
        )
        for name, rows in selected.items():
            if rows or not name.startswith("inv_quant_"):
                counts[name] = len(rows)
            candidates.update(_refs(rows))
        permits = []
        compact = session.bind.dialect.name == "sqlite"
        for name, rows in selected.items():
            for row in rows:
                permits.append(
                    {
                        "table_name": name,
                        "row_key": json.dumps(
                            [row[column.name] for column in tables[name].primary_key],
                            ensure_ascii=False,
                            separators=(",", ":") if compact else (", ", ": "),
                        ),
                    }
                )
        if permits:
            session.execute(DeletionPermitRow.__table__.insert(), permits)
        # Break the only RESTRICT ownership cycle (claim -> latest validation -> claim).
        session.execute(
            update(ClaimRow).where(ClaimRow.run_id.in_(run_ids)).values(latest_validation_id=None)
        )
        # Metadata dependencies include self-links; nullable SET NULL links need no ordering.
        remaining = {name for name, rows in selected.items() if rows}
        while remaining:
            leaves = []
            for parent in remaining:
                blocked = any(
                    fk.column.table.name == parent
                    and fk.ondelete != "SET NULL"
                    and not (child == "inv_claims" and fk.parent.name == "latest_validation_id")
                    for child in remaining
                    if child != parent
                    for fk in tables[child].foreign_keys
                )
                if not blocked:
                    leaves.append(parent)
            if not leaves:
                raise RuntimeError("archive deletion dependency cycle; transaction rolled back")
            for name in leaves:
                table = tables[name]
                predicates = [
                    and_(*(column == row[column.name] for column in table.primary_key))
                    for row in selected[name]
                ]
                # Bound SQL parameter count for large histories.
                for start in range(0, len(predicates), 100):
                    session.execute(delete(table).where(or_(*predicates[start : start + 100])))
                remaining.remove(name)
        for permit in permits:
            session.execute(
                delete(DeletionPermitRow).where(
                    DeletionPermitRow.table_name == permit["table_name"],
                    DeletionPermitRow.row_key == permit["row_key"],
                )
            )
    removed = 0
    deferred = 0
    if blobs and candidates:
        # GC after durable row deletion, under a second writer lock. Any active
        # writer makes GC conservative: retain orphans rather than race publication.
        with sessions.begin() as session:
            _lock(session)
            busy = session.scalar(
                select(InvestigationRunRow.run_id)
                .where(
                    or_(
                        InvestigationRunRow.status.in_(ACTIVE),
                        and_(
                            InvestigationRunRow.status == RunStatus.READY_FOR_REPORT,
                            InvestigationRunRow.completed_at.is_(None),
                        ),
                        InvestigationRunRow.owner_instance_id.is_not(None),
                    )
                )
                .limit(1)
            )
            if busy or session.bind.dialect.name != "sqlite":
                # Only SQLite currently has the publication/GC writer lock.
                # Other engines retain files until offline reference-safe GC.
                deferred = len(candidates)
            else:
                referenced = set()
                for table in Base.metadata.tables.values():
                    for row in session.execute(select(table)).mappings():
                        referenced.update(_refs(dict(row)))
                for uri in sorted(candidates - referenced):
                    try:
                        removed += blobs.delete_unreferenced(BlobRef.from_uri(uri))
                    except Exception as error:
                        deferred += 1
                        LOG.warning("Archive blob cleanup deferred (%s)", type(error).__name__)
    return {
        "investigation_id": investigation_id,
        "deleted": True,
        "already_deleted": False,
        "deleted_records": counts,
        "deleted_blobs": removed,
        "deferred_blobs": deferred,
    }
