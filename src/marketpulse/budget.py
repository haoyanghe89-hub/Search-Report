from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from marketpulse.config import Settings
from marketpulse.errors import BudgetExceeded


@dataclass
class RunBudget:
    started_at: float
    deadline: float
    max_search_queries: int
    max_pages: int
    clock: Callable[[], float]
    search_queries_used: int = 0
    pages_used: int = 0

    @classmethod
    def start(cls, settings: Settings, clock: Callable[[], float] = time.monotonic) -> RunBudget:
        now = clock()
        return cls(
            started_at=now,
            deadline=now + settings.total_timeout_seconds,
            max_search_queries=settings.max_search_queries,
            max_pages=settings.max_pages,
            clock=clock,
        )

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.clock() - self.started_at)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def ensure_time_remaining(self) -> None:
        if self.clock() >= self.deadline:
            raise BudgetExceeded("wall_time")

    def reserve_search(self) -> None:
        self.ensure_time_remaining()
        if self.search_queries_used >= self.max_search_queries:
            raise BudgetExceeded("search_queries")
        self.search_queries_used += 1

    def reserve_page(self) -> None:
        self.ensure_time_remaining()
        if self.pages_used >= self.max_pages:
            raise BudgetExceeded("pages")
        self.pages_used += 1
