"""Worker-only exhibit cells: no front-end financial computation."""

from decimal import localcontext

from .metrics import metric, prices


def price_cells(series, spec):
    result, high, incomplete = [], None, False
    with localcontext() as context:
        context.prec = 40
        for point, price in zip(series.points, prices(series, spec), strict=True):
            incomplete = incomplete or price is None
            high = max(high, price) if high is not None and price is not None else price
            drop = (
                price / high - 1
                if high is not None and price is not None and not incomplete
                else None
            )
            for kind, value, unit, definition in (
                ("price", price, "CNY/share", "frozen_close;suspension=" + spec.suspension_policy),
                ("drawdown", drop, "fraction", "P/running_max(P)-1;missing=propagate"),
            ):
                result.append(
                    metric(
                        series,
                        f"chart_{kind}_{series.adjustment}",
                        value,
                        unit,
                        definition,
                        reason="missing_price" if value is None else None,
                        count=1,
                        row_keys=(point.session_date.isoformat(),),
                    ).model_copy(update={"start": point.session_date, "end": point.session_date})
                )
    return result
