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
