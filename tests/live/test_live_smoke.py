from __future__ import annotations

import os
from pathlib import Path

import pytest

from marketpulse.cli import _execute
from marketpulse.config import Settings


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_smoke(tmp_path: Path) -> None:
    if os.getenv("RUN_LIVE_TESTS") != "1" or not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("set RUN_LIVE_TESTS=1 and DEEPSEEK_API_KEY to run")
    output = tmp_path / "live-report.md"
    settings = Settings.from_env()
    await _execute("AI meeting notes tools", output, 3, None, settings)
    report = output.read_text(encoding="utf-8")
    assert report.count("\n## ") == 10
    assert "Go / Conditional Go / No-Go" in report
    assert report.count("http") >= 8
