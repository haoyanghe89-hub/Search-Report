from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class Stage(StrEnum):
    PLAN = "plan"
    SEARCH = "search"
    FETCH = "fetch"
    EXTRACT = "extract"
    ANALYZE = "analyze"
    REVIEW = "review"
    REPORT = "report"
    QUALITY = "quality"
    WRITE = "write"


@dataclass
class RunStats:
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    search_queries: int = 0
    candidates: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    sources: int = 0
    warnings: list[str] = field(default_factory=list)


_SENSITIVE_FRAGMENTS = ("key", "token", "secret", "authorization", "password")


def redact_sensitive(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: "***REDACTED***"
        if any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS)
        else value
        for key, value in values.items()
    }


class RunLogger:
    def __init__(self, run_id: str, log_file: Path | None = None) -> None:
        self.run_id = run_id
        self.log_file = log_file
        self._logger = logging.getLogger("marketpulse")

    def event(self, stage: Stage, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "stage": stage.value,
            "event": event,
            **redact_sensitive(fields),
        }
        message = json.dumps(record, ensure_ascii=False, default=str)
        self._logger.info(message)
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(message + "\n")

    def snapshot(self, stats: RunStats) -> dict[str, Any]:
        return asdict(stats)
