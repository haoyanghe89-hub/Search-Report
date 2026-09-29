from datetime import UTC, datetime

import pytest

from marketpulse.investigation.domain.runtime import RunBudget
from marketpulse.investigation.feedback.budget_diagnostics import describe_budget_exhaustion


def budget(**changes: int) -> RunBudget:
    fields = dict(
        max_research_rounds=6,
        max_search_calls=240,
        max_fetch_calls=600,
        max_model_calls=480,
        max_tokens=2000000,
        max_wall_time_ms=3600000,
        max_sources=600,
    )
    fields.update(changes)
    return RunBudget(run_id="RUN-budget", updated_at=datetime.now(UTC), **fields)


@pytest.mark.parametrize(
    ("counter", "limit", "dimension"),
    (
        ("search_calls_used", "max_search_calls", "search_calls"),
        ("fetch_calls_used", "max_fetch_calls", "fetch_calls"),
        ("model_calls_used", "max_model_calls", "model_calls"),
        ("tokens_used", "max_tokens", "tokens"),
        ("sources_used", "max_sources", "sources"),
        ("consumed_wall_time_ms", "max_wall_time_ms", "wall_time_ms"),
    ),
)
def test_exhausted_dimension_and_usage(counter: str, limit: str, dimension: str) -> None:
    item = budget(**{counter: 10, limit: 10})
    message = describe_budget_exhaustion(item)
    assert f"：{dimension}。" in message
    assert "10/10" in message
    assert "BUDGET_EXHAUSTED" in message


def test_round_at_limit_can_finish_but_next_round_cannot() -> None:
    item = budget(research_rounds_used=6)
    assert "research_rounds" not in describe_budget_exhaustion(item, requested_round=6)
    message = describe_budget_exhaustion(item, requested_round=7)
    assert "research_rounds" in message
    assert "轮次 6/6（请求第 7 轮）" in message


def test_reservation_rejection_does_not_invent_exhausted_counter() -> None:
    item = budget(tokens_used=1999000)
    message = describe_budget_exhaustion(item, rejected_dimension="token reservation")
    assert "计数器尚未达上限" in message
    assert "Token 1999000/2000000" in message
    assert "拒绝原因：token reservation" in message


def test_reports_all_exhausted_dimensions() -> None:
    message = describe_budget_exhaustion(budget(search_calls_used=240, model_calls_used=480))
    assert "search_calls, model_calls" in message
