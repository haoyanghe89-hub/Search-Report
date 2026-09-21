from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from marketpulse.investigation.domain.enums import (
    ParseStatus,
    RunMode,
    RunStatus,
    SourceType,
    WorkflowPhase,
)
from marketpulse.investigation.persistence.base import create_investigation_engine
from marketpulse.investigation.persistence.models import (
    InvestigationRow,
    InvestigationRunRow,
    SourceRow,
    SourceSnapshotRow,
)


@pytest.mark.infrastructure
def test_postgres_migration_and_snapshot_foreign_keys() -> None:
    url = os.getenv("MARKETPULSE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set MARKETPULSE_TEST_POSTGRES_URL to a dedicated test database")

    root = Path(__file__).resolve().parents[3]
    config = Config(root / "alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")

    suffix = uuid.uuid4().hex
    now = datetime.now(UTC)
    digest = hashlib.sha256(suffix.encode()).hexdigest()
    engine = create_investigation_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            InvestigationRow.__table__.insert().values(
                investigation_id=f"I-{suffix}",
                title="PostgreSQL smoke",
                event_description="Integration verification",
                investigation_goal="Validate schema types and foreign keys",
                scope={"summary": "PostgreSQL"},
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            InvestigationRunRow.__table__.insert().values(
                run_id=f"RUN-{suffix}",
                investigation_id=f"I-{suffix}",
                mode=RunMode.LIVE,
                status=RunStatus.RUNNING,
                current_phase=WorkflowPhase.COLLECT,
                checkpoint_version=0,
                state_version=0,
                workflow_version="v1",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            SourceRow.__table__.insert().values(
                source_id=f"S-{suffix}",
                investigation_id=f"I-{suffix}",
                canonical_url=f"https://example.test/{suffix}",
                title="PostgreSQL source",
                source_type=SourceType.OFFICIAL_REPORT,
                is_official=True,
                is_first_hand=True,
                discovered_at=now,
            )
        )
        connection.execute(
            SourceSnapshotRow.__table__.insert().values(
                snapshot_id=f"SS-{suffix}",
                source_id=f"S-{suffix}",
                run_id=f"RUN-{suffix}",
                retrieved_at=now,
                raw_blob_ref=f"blob://sha256/{digest}",
                raw_sha256=digest,
                cleaned_blob_ref=f"blob://sha256/{digest}",
                cleaned_sha256=digest,
                mime_type="text/plain",
                encoding="utf-8",
                content_size=len(suffix),
                http_status=200,
                parse_status=ParseStatus.PARSED,
                parser_name="fixture",
                parser_version="1",
                normalizer_version="1",
                evidence_eligible=True,
                provenance={"test": "postgresql"},
            )
        )
        assert (
            connection.scalar(
                select(SourceSnapshotRow.snapshot_id).where(
                    SourceSnapshotRow.snapshot_id == f"SS-{suffix}"
                )
            )
            == f"SS-{suffix}"
        )
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
