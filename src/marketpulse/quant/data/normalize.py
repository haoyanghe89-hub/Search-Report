from __future__ import annotations

import math
from datetime import datetime

from ..contracts import canonical
from ..domain import DataRequest
from .pit import visible_financial

DAILY_FIELDS = {
    "date": "date",
    "日期": "date",
    "open": "open",
    "开盘": "open",
    "high": "high",
    "最高": "high",
    "low": "low",
    "最低": "low",
    "close": "close",
    "收盘": "close",
    "volume": "volume",
    "成交量": "volume",
    "amount": "amount",
    "成交额": "amount",
    "turn": "turnover",
    "换手率": "turnover",
    "turnover": "turnover",
    "tradestatus": "trading_status",
    "isST": "is_st",
    "peTTM": "pe_ttm",
    "pbMRQ": "pb_mrq",
    "pctChg": "return_fraction",
    "涨跌幅": "return_fraction",
    "preclose": "previous_close",
}
FINANCIAL_FIELDS = {
    "statDate": "period_end",
    "pubDate": "published_at",
    "netProfit": "net_profit",
    "epsTTM": "eps_ttm",
    "MBRevenue": "revenue",
    "gpMargin": "gross_margin",
    "npMargin": "net_margin",
    "roeAvg": "roe",
    "totalShare": "total_shares",
    "liqaShare": "liquid_shares",
}
FACTOR_FIELDS = {
    "dividOperateDate": "date",
    "foreAdjustFactor": "forward_factor",
    "backAdjustFactor": "backward_factor",
    "adjustFactor": "adjustment_factor",
}
VALUE_FIELDS = {
    "数据日期": "date",
    "当日收盘价": "close",
    "总市值": "market_cap",
    "流通市值": "float_market_cap",
    "总股本": "total_shares",
    "流通股本": "float_shares",
    "市净率": "pb_mrq",
    "PE(TTM)": "pe_ttm",
    "PE(静)": "pe_static",
}
UNITS = {
    "open": "CNY/share",
    "high": "CNY/share",
    "low": "CNY/share",
    "close": "CNY/share",
    "previous_close": "CNY/share",
    "volume": "share",
    "amount": "CNY",
    "turnover": "fraction",
    "return_fraction": "fraction",
    "net_profit": "CNY",
    "revenue": "CNY",
    "eps_ttm": "CNY/share",
    "gross_margin": "fraction",
    "net_margin": "fraction",
    "roe": "fraction",
    "total_shares": "share",
    "liquid_shares": "share",
    "float_shares": "share",
    "market_cap": "CNY",
    "float_market_cap": "CNY",
    "pe_ttm": "ratio",
    "pe_static": "ratio",
    "pb_mrq": "ratio",
    "forward_factor": "ratio",
    "backward_factor": "ratio",
    "adjustment_factor": "ratio",
}


def number(value: object) -> float | None:
    if value is None or str(value).strip() in {"", "--", "None", "nan", "NaN", "NaT", "-"}:
        return None
    result = float(str(value).replace(",", ""))
    return result if math.isfinite(result) else None


def iso_date(value: object) -> str:
    text = str(value)[:10]
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return datetime.strptime(text, "%Y-%m-%d").date().isoformat()


def normalize(
    raw: list[dict],
    request: DataRequest,
    provider: str,
    instrument_id: str,
    source_units: dict[str, str] | None = None,
) -> tuple[list[dict], tuple[tuple[str, str], ...]]:
    if request.dataset == "calendar":
        return [
            {
                "date": iso_date(row["calendar_date"]),
                "is_session": str(row["is_trading_day"]) == "1",
                "instrument_id": instrument_id,
            }
            for row in raw
        ], ()
    if request.dataset == "instrument_master":
        return [
            {
                "instrument_id": instrument_id,
                "code": row.get("code"),
                "name": row.get("code_name"),
                "listed_at": iso_date(row["ipoDate"]) if row.get("ipoDate") else None,
                "delisted_at": iso_date(row["outDate"]) if row.get("outDate") else None,
                "type": row.get("type"),
                "status": row.get("status"),
            }
            for row in raw
        ], ()
    mapping = {
        "daily": DAILY_FIELDS,
        "financial": FINANCIAL_FIELDS,
        "adjustment": FACTOR_FIELDS,
        "valuation": VALUE_FIELDS,
    }[request.dataset]
    records = []
    if request.normalizer_version == "3-parent-2" and provider == "akshare_eastmoney":
        from .financial_normalize import BASIS, normalize_parent

        if request.dataset == "financial":
            return normalize_parent(raw, request, instrument_id)
    if (
        request.dataset == "financial"
        and provider == "akshare_eastmoney"
        and request.normalizer_version == "3"
    ):
        # Preserve the native statement for audit before asserting numeric semantics.
        # v2 / Sina normalization and all existing frozen payloads remain unchanged.
        for item in raw:
            period = iso_date(item["REPORT_DATE"])
            if request.start.isoformat() <= period <= request.end.isoformat():
                published = item.get("NOTICE_DATE")
                row = {
                    "instrument_id": instrument_id,
                    "period_end": period,
                    "published_at": iso_date(published) if published else None,
                    "metric": "balance_sheet"
                    if "balance_sheet" in request.fields
                    else "income_statement",
                    "native_statement": item,
                }
                if visible_financial(row, request.asof.date()):
                    records.append(row)
        return sorted(records, key=canonical), ()
    if request.dataset == "financial" and provider.startswith("akshare"):
        # Sina wide financial abstract has no publication-time provenance. Keep native
        # metric label (unit not asserted), never invent currency or PIT dates.
        for item in raw:
            for key, value in item.items():
                if len(key) == 8 and key.isdigit():
                    period = iso_date(key)
                    if request.start.isoformat() <= period <= request.end.isoformat():
                        records.append(
                            {
                                "instrument_id": instrument_id,
                                "period_end": period,
                                "metric": item.get("指标"),
                                "value": number(value),
                                "published_at": None,
                                "unit": "unknown",
                            }
                        )
        return records, (("value", "unknown"),)
    for item in raw:
        row: dict = {"instrument_id": instrument_id}
        for original, normalized in mapping.items():
            if original not in item:
                continue
            value = item[original]
            if normalized in {"date", "period_end", "published_at"}:
                row[normalized] = iso_date(value) if value else None
            elif normalized in {"trading_status", "is_st"}:
                row[normalized] = bool(int(value)) if str(value).strip() else None
            else:
                row[normalized] = number(value)
        stamp = row.get("date") or row.get("period_end")
        if not stamp or not request.start.isoformat() <= stamp <= request.end.isoformat():
            continue
        if request.dataset == "financial" and not visible_financial(row, request.asof.date()):
            continue
        if provider.startswith("akshare") and request.dataset == "daily":
            if row.get("volume") is not None:
                unit = (source_units or {}).get(
                    "volume", "share" if provider == "akshare_tencent" else "hand"
                )
                if unit == "hand":
                    row["volume"] *= 100
                elif unit != "share":
                    raise ValueError("unknown source volume unit")
        if request.dataset == "daily":
            for field in ("turnover", "return_fraction"):
                if row.get(field) is not None and not (
                    provider == "akshare_tencent" and field == "turnover"
                ):
                    row[field] /= 100
            # Tencent amount may be absent; absent data is never zero-filled.
            for field in ("volume", "amount", "trading_status", "is_st", "pe_ttm", "pb_mrq"):
                row.setdefault(field, None)
        if request.dataset == "valuation":
            # stock_value_em documents cap as yuan, shares as shares (no implicit 万/亿).
            if request.normalizer_version == "3-parent-2":
                from datetime import time
                from zoneinfo import ZoneInfo

                row.update(
                    available_at=datetime.combine(
                        datetime.fromisoformat(row["date"]).date(),
                        time(15),
                        ZoneInfo("Asia/Shanghai"),
                    ).isoformat(),
                    availability_basis="historical_session_close_label_not_first_seen",
                    published_at=None,
                    share_basis=BASIS,
                    statement_basis="parent",
                    period_basis="point",
                )
        row["provisional"] = False
        records.append(row)
    fields = {key for row in records for key in row}
    return sorted(records, key=canonical), tuple(
        sorted((k, v) for k, v in UNITS.items() if k in fields)
    )
