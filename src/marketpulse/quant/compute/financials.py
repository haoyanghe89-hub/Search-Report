"""Same-basis TTM and year-on-year calculations, without data access."""

import calendar
from datetime import date, timedelta
from decimal import localcontext

from ..contracts import digest


def same_basis(facts):
    return (
        bool(facts)
        and all(f.value is not None for f in facts)
        and len({(f.unit, f.share_basis, f.statement_basis) for f in facts}) == 1
        and facts[0].share_basis != "unknown"
    )


def ttm_profit(facts):
    profits = [f for f in facts if f.metric == "parent_net_profit"]
    if not profits:
        return None
    end = max(f.period_end for f in profits)
    current = [f for f in profits if f.period_end == end]
    if len(current) != 1:
        return None
    last = current[0]
    if last.period_basis == "ttm":
        return last
    selected = []
    with localcontext() as ctx:
        ctx.prec = 40
        if last.period_basis == "quarter" and end.month in {3, 6, 9, 12}:
            ordinal = end.year * 4 + end.month // 3 - 1
            for i in range(4):
                year, quarter = divmod(ordinal - i, 4)
                month = (quarter + 1) * 3
                stamp = date(year, month, calendar.monthrange(year, month)[1])
                matches = [
                    f for f in profits if f.period_end == stamp and f.period_basis == "quarter"
                ]
                if len(matches) != 1:
                    return None
                selected.append(matches[0])
            amount = sum(f.value for f in selected) if same_basis(selected) else None
            begin = selected[-1].period_start
        elif last.period_basis in {"annual", "ytd"} and end.month == 12:
            selected, amount, begin = [last], last.value, date(end.year, 1, 1)
        elif last.period_basis == "ytd":
            previous_annual = [
                f
                for f in profits
                if f.period_end == date(end.year - 1, 12, 31)
                and f.period_basis in {"annual", "ytd"}
            ]
            previous_ytd = [
                f
                for f in profits
                if f.period_end == end.replace(year=end.year - 1) and f.period_basis == "ytd"
            ]
            if len(previous_annual) != 1 or len(previous_ytd) != 1:
                return None
            selected = [last, previous_annual[0], previous_ytd[0]]
            amount = (
                selected[1].value + last.value - selected[2].value if same_basis(selected) else None
            )
            begin = previous_ytd[0].period_end + timedelta(days=1)
        else:
            return None
    if (
        amount is None
        or not begin
        or not same_basis(selected)
        or any(f.statement_basis != "parent" for f in selected)
    ):
        return None
    return last.model_copy(
        update={
            "value": amount,
            "period_basis": "ttm",
            "period_start": begin,
            "revision": "derived:" + digest([f.model_dump(mode="json") for f in selected]),
            "source_hash": digest([f.source_hash for f in selected]),
        }
    )


def yoy_growth(facts, metric):
    observations = [f for f in facts if f.metric == metric]
    if not observations:
        return None, "insufficient_yoy_history"
    end = max(f.period_end for f in observations)
    previous_day = date(
        end.year - 1, end.month, min(end.day, calendar.monthrange(end.year - 1, end.month)[1])
    )
    new = [f for f in observations if f.period_end == end]
    old = [f for f in observations if f.period_end == previous_day]
    if len(new) != 1 or len(old) != 1:
        return None, "insufficient_yoy_history"
    if not same_basis((new[0], old[0])) or new[0].period_basis != old[0].period_basis:
        return None, "incomparable_periods"
    if old[0].value <= 0:
        return None, "nonpositive_comparison_base"
    with localcontext() as ctx:
        ctx.prec = 40
        return new[0].value / old[0].value - 1, None
