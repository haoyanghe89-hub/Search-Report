"""Explicit Eastmoney parent-aggregate accounting, not EPS-inferred fundamentals."""

from datetime import date
from decimal import Decimal

from ..contracts import canonical, digest

BASIS = "total_issued_shares_parent_aggregate_not_ordinary_eps"
FIELDS = {
    "PARENT_NETPROFIT": "parent_net_profit",
    "TOTAL_PARENT_EQUITY": "parent_equity",
    "OPERATE_INCOME": "revenue",
    "OTHER_EQUITY_TOOL": "other_equity_instruments",
}


def exact(value):
    if value is None or str(value).strip() in {"", "--", "nan", "NaN", "-"}:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        return None
    return format(number, "f")


def normalize_parent(raw, request, instrument_id):
    records = []
    for item in raw:
        period = date.fromisoformat(str(item["REPORT_DATE"])[:10])
        published = str(item.get("NOTICE_DATE") or "")[:10]
        if not request.start <= period <= request.end or not published:
            continue
        if date.fromisoformat(published) >= request.asof.date():
            continue
        currency = item.get("CURRENCY")
        if currency != "CNY":
            raise ValueError("explicit CNY statement required; no currency inference")
        income = "income_statement" in request.fields
        row = {
            "instrument_id": instrument_id,
            "period_end": period.isoformat(),
            "period_start": date(period.year, 1, 1).isoformat() if income else None,
            "period_basis": "annual"
            if income and period.month == 12
            else "ytd"
            if income
            else "point",
            "published_at": published,
            "metric": "income_statement" if income else "balance_sheet",
            "income_statement": True if income else None,
            "balance_sheet": True if not income else None,
            "share_basis": BASIS,
            "statement_basis": "parent",
            "metric_basis": {"revenue": "consolidated"},
            "currency": "CNY",
            "revision": str(item.get("UPDATE_DATE") or "unknown"),
            "source_hash": digest(item),
            "native_fields": {key: item.get(key) for key in FIELDS},
            "equity_definition": "total_parent_equity_including_other_equity_instruments",
            "earnings_definition": "parent_net_profit_before_preferred_or_perpetual_distributions",
            "ordinary_eps_comparable": False,
        }
        for source, target in FIELDS.items():
            if source in item:
                row[target] = exact(item[source])
        records.append(row)
    present = {key for r in records for key in r}
    return sorted(records, key=canonical), tuple(
        sorted((key, "CNY") for key in FIELDS.values() if key in present)
    )
