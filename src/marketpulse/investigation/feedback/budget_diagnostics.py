from __future__ import annotations

from marketpulse.investigation.domain.runtime import RunBudget


def describe_budget_exhaustion(
    budget: RunBudget,
    *,
    requested_round: int | None = None,
    rejected_dimension: str | None = None,
) -> str:
    """Explain a budget stop without changing limits or accounting.

    Reservations can fail before a counter reaches its limit (for example when
    an entire model output allowance will not fit). Callers may supply that
    rejection reason; counters alone must not invent the failed dimension.
    A round already started is permitted to finish at the round limit.
    """
    counters = (
        ("search_calls", "搜索", budget.search_calls_used, budget.max_search_calls),
        ("fetch_calls", "抓取", budget.fetch_calls_used, budget.max_fetch_calls),
        ("model_calls", "模型调用", budget.model_calls_used, budget.max_model_calls),
        ("tokens", "Token", budget.tokens_used, budget.max_tokens),
        ("sources", "来源", budget.sources_used, budget.max_sources),
        ("wall_time_ms", "执行时间(ms)", budget.consumed_wall_time_ms, budget.max_wall_time_ms),
    )
    exhausted = [key for key, _, used, maximum in counters if used >= maximum]
    if (
        requested_round is not None and requested_round > budget.max_research_rounds
    ) or budget.research_rounds_used > budget.max_research_rounds:
        exhausted.append("research_rounds")
    dimensions = ", ".join(exhausted) or "下一次操作所需额度不足（计数器尚未达上限）"
    usage = "；".join(f"{label} {used}/{maximum}" for _, label, used, maximum in counters)
    usage += f"；轮次 {budget.research_rounds_used}/{budget.max_research_rounds}"
    if requested_round is not None:
        usage += f"（请求第 {requested_round} 轮）"
    detail = f"；拒绝原因：{rejected_dimension}" if rejected_dimension else ""
    return f"预算不足（BUDGET_EXHAUSTED）：{dimensions}。已用/上限：{usage}{detail}"
