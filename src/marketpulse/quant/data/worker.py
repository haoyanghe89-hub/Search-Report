"""Only SDK boundary. One bounded process/session, never imported by FastAPI."""

from __future__ import annotations

import json
import socket
import sys


def execute(query: dict) -> dict:
    socket.setdefaulttimeout(12)
    import requests

    original = requests.sessions.Session.request

    def bounded(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 12)
        return original(self, method, url, **kwargs)

    requests.sessions.Session.request = bounded
    request = query["request"]
    start, end = request["start"], request["end"]
    dataset, adjustment = request["dataset"], request["adjustment"]
    code, exchange = query["code"], query["exchange"]
    prefix = "sh" if exchange == "XSHG" else "sz"
    provider = query["provider"]
    if provider == "baostock":
        import baostock as bs

        if bs.login().error_code != "0":
            raise RuntimeError("BaoStock login failed")
        try:
            results = []
            if dataset == "calendar":
                return {"rows": consume(bs.query_trade_dates(start, end))}
            if dataset == "instrument_master":
                return {"rows": consume(bs.query_stock_basic(code=f"{prefix}.{code}"))}
            if dataset == "daily":
                results.append(
                    bs.query_history_k_data_plus(
                        f"{prefix}.{code}",
                        "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
                        "tradestatus,pctChg,peTTM,pbMRQ,isST",
                        start_date=start,
                        end_date=end,
                        frequency="d",
                        adjustflag="3",
                    )
                )
            elif dataset == "adjustment":
                results.append(bs.query_adjust_factor(f"{prefix}.{code}", start, end))
            elif dataset == "financial":
                rows = []
                for year in range(int(start[:4]), int(end[:4]) + 1):
                    for quarter in range(1, 5):
                        response = bs.query_profit_data(f"{prefix}.{code}", year, quarter)
                        rows.extend(consume(response))
                return {"rows": rows}
            else:
                raise ValueError("BaoStock valuation uses daily PE/PB; request daily")
            rows = [row for result in results for row in consume(result)]
            factors = []
            if dataset == "daily" and adjustment != "raw":
                factors = consume(
                    bs.query_adjust_factor(
                        f"{prefix}.{code}", "1990-01-01", request["adjustment_anchor"]
                    )
                )
            return {"rows": rows, "factors": factors}
        finally:
            bs.logout()
    import akshare as ak

    if dataset == "daily":
        options = dict(
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="" if adjustment == "raw" else adjustment,
            timeout=12,
        )
        if provider == "akshare_tencent":
            frame = ak.stock_zh_a_hist_tx(symbol=prefix + code, **options)
        elif provider == "akshare_eastmoney":
            frame = ak.stock_zh_a_hist(symbol=code, **options)
        else:
            raise ValueError("unsupported daily provider")
    elif dataset == "financial" and provider == "akshare_sina":
        frame = ak.stock_financial_abstract(symbol=code)
    elif dataset == "financial" and provider == "akshare_eastmoney":
        if request["normalizer_version"] not in {"3", "3-parent-2"}:
            raise ValueError("explicit financial normalizer v3 required")
        symbol = prefix.upper() + code
        if "balance_sheet" in request["fields"]:
            frame = ak.stock_balance_sheet_by_report_em(symbol=symbol)
        elif "income_statement" in request["fields"]:
            frame = ak.stock_profit_sheet_by_report_em(symbol=symbol)
        else:
            raise ValueError("explicit statement type required")
    elif dataset == "valuation" and provider == "akshare_eastmoney":
        frame = ak.stock_value_em(symbol=code)
    else:
        raise ValueError("unsupported provider dataset")
    # Preserve native units and dates, make NaN/null and numpy scalars JSON-safe.
    source_units = {}
    if dataset == "daily":
        source_units["volume"] = (
            "hand"
            if provider == "akshare_eastmoney"
            else "hand"
            if (prefix + code).startswith(("sh688", "sz000"))
            else "share"
        )
    return {
        "rows": json.loads(frame.to_json(orient="records", date_format="iso", force_ascii=False)),
        "source_units": source_units,
    }


def consume(response) -> list[dict]:
    if response.error_code != "0":
        raise RuntimeError("BaoStock query failed")
    rows = []
    while response.next():
        rows.append(dict(zip(response.fields, response.get_row_data(), strict=True)))
        if len(rows) > 5000:
            raise ValueError("provider row bound exceeded")
    if response.error_code != "0":
        raise RuntimeError("BaoStock stream failed")
    return rows


if __name__ == "__main__":
    try:
        value = execute(json.loads(sys.stdin.buffer.read(65536)))
    except Exception as error:
        value = {"error": type(error).__name__}
    print("QUANT_JSON:" + json.dumps(value, ensure_ascii=False), flush=True)
