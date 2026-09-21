from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from marketpulse.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        deepseek_api_key="test-key",
        total_timeout_seconds=300,
        max_search_queries=12,
        max_pages=24,
        max_retries=2,
        database_url=f"sqlite:///{(tmp_path / 'blackboard.db').as_posix()}",
    )


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Tests never load the user's project .env or use its state database.
    monkeypatch.setenv("MARKETPULSE_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("MARKETPULSE_DATABASE_URL", f"sqlite:///{tmp_path.as_posix()}/api.db")
    monkeypatch.delenv("MARKETPULSE_REDIS_URL", raising=False)


@pytest.fixture
def ticking_clock() -> Iterator[tuple[list[float], object]]:
    value = [100.0]

    def now() -> float:
        return value[0]

    yield value, now
