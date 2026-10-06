from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext

from ..domain import MetricSpec, MetricValue, PriceSeries


def prices(series: PriceSeries, spec: MetricSpec) -> tuple[Decimal | None, ...]:
    values = []
    previous = None
    for point in series.points:
        value = point.close
        if point.suspended:
            value = previous if spec.suspension_policy == "carry_forward" else None
        values.append(value)
        previous = value
    return tuple(values)


def metric(series, name, value, unit, definition, *, reason=None, count=None, **extra):
    return MetricValue(
        name=name,
        value=value,
        unit=unit,
        definition=definition,
        sample_count=len(series.points) if count is None else count,
        instrument_id=series.instrument_id,
        start=series.points[0].session_date,
        end=series.points[-1].session_date,
        missing_reason=reason,
        **extra,
    )


def compute_metrics(
    *,
    series: PriceSeries,
    spec: MetricSpec,
    benchmark: PriceSeries | None = None,
    risk_free: tuple[tuple[date, Decimal], ...] = (),
) -> tuple[MetricValue, ...]:
    with localcontext() as context:
        context.prec = 40
        ps = prices(series, spec)
        if (series.adjustment == "raw") != (spec.return_basis == "price"):
            raise ValueError("return basis does not match price adjustment")
        returns = [None] + [
            b / a - 1 if a is not None and b is not None else None
            for a, b in zip(ps, ps[1:], strict=False)
        ]
        common = f"basis={spec.return_basis};suspension={spec.suspension_policy};missing=propagate"
        result = [
            metric(
                series,
                "daily_return",
                value,
                "fraction",
                "P[t]/P[t-1]-1;" + common,
                reason="first_observation"
                if i == 0
                else "missing_price"
                if value is None
                else None,
                count=0 if i == 0 else 1,
                row_keys=(p.session_date.isoformat(),),
            )
            for i, (p, value) in enumerate(zip(series.points, returns, strict=False))
        ]
        valid = len(ps) >= 2 and all(p is not None for p in ps)
        reason = "missing_price" if not valid else None
        cumulative = ps[-1] / ps[0] - 1 if valid else None
        if "return" in spec.metrics:
            result.append(
                metric(
                    series,
                    "return",
                    cumulative,
                    "fraction",
                    "product(1+r)-1;" + common,
                    reason=reason,
                )
            )
        days = (series.points[-1].session_date - series.points[0].session_date).days
        if "cagr" in spec.metrics:
            cagr = (
                ((1 + cumulative).ln() * spec.elapsed_year_days / days).exp() - 1
                if valid and days
                else None
            )
            result.append(
                metric(
                    series,
                    "cagr",
                    cagr,
                    "fraction/year",
                    f"(last/first)^(1/elapsed_years)-1;year_days={spec.elapsed_year_days};"
                    + common,
                    reason=reason or ("zero_elapsed_time" if not days else None),
                )
            )
        daily = returns[1:]
        enough = valid and len(daily) >= 2
        mean = sum(daily) / len(daily) if enough else None
        std = (sum((r - mean) ** 2 for r in daily) / (len(daily) - 1)).sqrt() if enough else None
        if "volatility" in spec.metrics:
            result.append(
                metric(
                    series,
                    "volatility",
                    std * Decimal(spec.annual_sessions).sqrt() if enough else None,
                    "fraction/sqrt(year)",
                    f"sample_std(ddof=1)*sqrt({spec.annual_sessions});" + common,
                    reason=reason or ("insufficient_returns" if not enough else None),
                    count=len(daily),
                )
            )
        if "drawdown" in spec.metrics:
            peak = trough = recovery = None
            dd = None
            if valid:
                high, high_index, worst, peak_i, trough_i = ps[0], 0, Decimal(0), 0, 0
                for i, p in enumerate(ps):
                    if p > high:
                        high, high_index = p, i
                    drop = p / high - 1
                    if drop < worst:
                        worst, peak_i, trough_i = drop, high_index, i
                dd = worst
                peak, trough = (
                    series.points[peak_i].session_date,
                    series.points[trough_i].session_date,
                )
                recovery = (
                    next(
                        (
                            series.points[i].session_date
                            for i in range(trough_i + 1, len(ps))
                            if ps[i] >= ps[peak_i]
                        ),
                        None,
                    )
                    if worst < 0
                    else None
                )
            result.append(
                metric(
                    series,
                    "drawdown",
                    dd,
                    "fraction",
                    "P/running_max(P)-1;worst;" + common,
                    reason=reason,
                    peak_date=peak,
                    trough_date=trough,
                    recovery_date=recovery,
                )
            )
        if "sharpe" in spec.metrics:
            rates = dict(risk_free)
            aligned = spec.explicit_zero_risk_free or all(
                p.session_date in rates for p in series.points[1:]
            )
            why = reason or (
                "missing_risk_free"
                if not aligned
                else "insufficient_returns"
                if not enough
                else None
            )
            excess = (
                [
                    r - (Decimal(0) if spec.explicit_zero_risk_free else rates[p.session_date])
                    for p, r in zip(series.points[1:], daily, strict=False)
                ]
                if not why
                else []
            )
            es_mean = sum(excess) / len(excess) if excess else None
            es_std = (
                (sum((r - es_mean) ** 2 for r in excess) / (len(excess) - 1)).sqrt()
                if excess
                else None
            )
            value = es_mean / es_std * Decimal(spec.annual_sessions).sqrt() if es_std else None
            result.append(
                metric(
                    series,
                    "sharpe",
                    value,
                    "ratio",
                    "daily_excess_mean/sample_std;sqrt(A);rf="
                    + ("explicit_user_zero" if spec.explicit_zero_risk_free else "snapshot"),
                    reason=why or ("zero_variance" if value is None else None),
                )
            )
        for name in ("beta", "correlation"):
            if name in spec.metrics:
                # P0 has no normalized benchmark contract; never substitute a ticker or zero.
                result.append(
                    metric(
                        series,
                        name,
                        None,
                        "ratio",
                        "same-session benchmark returns required",
                        reason="missing_benchmark"
                        if benchmark is None
                        else "benchmark_not_supported",
                    )
                )
        return tuple(result)
