from datetime import date
from decimal import Decimal

from ..domain import DataRequest


def anchored_prices(rows: list[dict], factors: list[dict], request: DataRequest) -> list[dict]:
    """Freeze provider action factors; qfq is rebased to request anchor, not today's latest."""
    anchor = request.adjustment_anchor
    if anchor is None:
        raise ValueError("adjustment anchor required")
    factors = sorted(
        (f for f in factors if date.fromisoformat(f["dividOperateDate"]) <= anchor),
        key=lambda f: f["dividOperateDate"],
    )
    if not factors:
        raise ValueError("no verified factor history")
    factor_field = "foreAdjustFactor" if request.adjustment == "qfq" else "backAdjustFactor"

    def at(day: str) -> Decimal:
        applicable = [f for f in factors if f["dividOperateDate"] <= day]
        if not applicable:
            raise ValueError("factor history does not cover first bar")
        factor = Decimal(applicable[-1][factor_field])
        if factor <= 0:
            raise ValueError("invalid adjustment factor")
        return factor

    denominator = at(anchor.isoformat()) if request.adjustment == "qfq" else Decimal(1)
    output = []
    for row in rows:
        ratio = at(row["date"]) / denominator
        item = dict(row)
        for field in ("open", "high", "low", "close", "previous_close"):
            if row.get(field) is not None:
                item[field] = float(Decimal(str(row[field])) * ratio)
        output.append(item)
    return output
