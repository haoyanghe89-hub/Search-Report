from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import localcontext
from zoneinfo import ZoneInfo

from ..domain import FinancialFact, PriceSeries
from .financials import ttm_profit
from .metrics import metric


def valuation_check(*, series: PriceSeries, financials: tuple[FinancialFact, ...], asof: datetime):
    if asof.tzinfo is None or asof.utcoffset() is None:
        raise ValueError("aware valuation cutoff required")
    cutoff = min(
        asof, datetime.combine(series.points[-1].session_date, time(15), ZoneInfo("Asia/Shanghai"))
    )
    facts = [
        f
        for f in financials
        if f.available_at and f.available_at <= cutoff and f.period_end <= cutoff.date()
    ]

    def latest(name):
        matches = [f for f in facts if f.metric == name]
        if not matches:
            return None
        last = max(f.period_end for f in matches)
        matches = [f for f in matches if f.period_end == last]
        return (
            matches[0] if len(matches) == 1 else None
        )  # ambiguous revisions are not silently latest

    shares, profit, equity = (
        latest("total_shares"),
        ttm_profit(facts),
        latest("parent_equity"),
    )
    beginning = latest("parent_equity_begin")
    if beginning is None and profit and profit.period_start:
        matches = [
            f
            for f in facts
            if f.metric == "parent_equity"
            and f.period_end == profit.period_start - timedelta(days=1)
        ]
        beginning = matches[0] if len(matches) == 1 else None
    with localcontext() as context:
        context.prec = 40
        results = []
        for name, denominator in (("pe", profit), ("pb", equity)):
            reason = None
            if series.adjustment != "raw":
                reason = "raw_price_required"
            elif not shares or not denominator or shares.value is None or denominator.value is None:
                reason = "missing_valuation_inputs"
            elif shares.unit != "share" or denominator.unit != series.currency:
                reason = "unit_mismatch"
            elif shares.share_basis == "unknown" or shares.share_basis != denominator.share_basis:
                reason = "share_basis_mismatch"
            elif (
                denominator.statement_basis != "parent"
                or shares.period_end != series.points[-1].session_date
            ):
                reason = "parent_basis_or_current_shares_missing"
            elif name == "pe" and denominator.period_basis != "ttm":
                reason = "ttm_required"
            elif denominator.value <= 0 or shares.value <= 0:
                reason = "nonpositive_earnings" if name == "pe" else "nonpositive_equity"
            elif series.points[-1].close is None:
                reason = "missing_price"
            value = (
                series.points[-1].close * shares.value / denominator.value if not reason else None
            )
            denominator_name = "TTM_parent_profit" if name == "pe" else "parent_equity"
            definition = f"raw_price*total_shares/{denominator_name};total_cap"
            if denominator:
                definition += (
                    f";period={denominator.period_end};revision={denominator.revision}"
                    f";basis={denominator.share_basis}"
                )
            if shares:
                definition += f";share_date={shares.period_end};share_basis={shares.share_basis}"
            results.append(metric(series, name, value, "ratio", definition, reason=reason))
            if shares and shares.share_basis.startswith("total_issued_shares_parent_aggregate"):
                results[-1] = results[-1].model_copy(
                    update={
                        "start": series.points[-1].session_date,
                        "end": series.points[-1].session_date,
                        "sample_count": 1,
                    }
                )
        reason = None
        if (
            not profit
            or not equity
            or not beginning
            or any(f.value is None for f in (profit, equity, beginning))
        ):
            reason = "missing_average_parent_equity"
        elif any(
            f.statement_basis != "parent" or f.unit != series.currency
            for f in (profit, equity, beginning)
        ):
            reason = "parent_unit_mismatch"
        elif (
            profit.period_basis != "ttm"
            or profit.period_end != equity.period_end
            or not profit.period_start
            or beginning.period_end != profit.period_start - timedelta(days=1)
        ):
            reason = "average_equity_period_mismatch"
        elif (
            profit.share_basis == "unknown"
            or len({f.share_basis for f in (profit, equity, beginning)}) != 1
        ):
            reason = "share_basis_mismatch"
        elif equity.value + beginning.value <= 0:
            reason = "nonpositive_average_equity"
        roe = profit.value / ((equity.value + beginning.value) / 2) if not reason else None
        results.append(
            metric(
                series,
                "roe",
                roe,
                "fraction",
                "computed_TTM_parent_profit/mean(begin,end_parent_equity)",
                reason=reason,
            )
        )
        if profit and profit.share_basis.startswith("total_issued_shares_parent_aggregate"):
            results[-1] = results[-1].model_copy(
                update={
                    "start": profit.period_start or profit.period_end,
                    "end": profit.period_end,
                    "sample_count": 1,
                }
            )
        return tuple(results)
