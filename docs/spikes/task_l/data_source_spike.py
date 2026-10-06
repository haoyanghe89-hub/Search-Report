"""Task L read-only provider feasibility probe; never imports business modules.

Run with the isolated environment documented in README.md. Provider failures are
evidence, not replaced with synthetic data. Network children have hard timeouts.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"
MARKER = "TASK_L_JSON:"
CASES = [
    "ak_em_raw",
    "ak_em_qfq",
    "ak_em_hfq",
    "ak_tx_raw",
    "ak_tx_qfq",
    "ak_tx_hfq",
    "ak_financial",
    "ak_valuation",
    "bao_raw",
    "bao_qfq",
    "bao_hfq",
    "bao_profit",
    "bao_factors",
]


def utc():
    return datetime.now(UTC).isoformat()


def probe(name):
    socket.setdefaulttimeout(12)
    import requests

    original = requests.sessions.Session.request

    def bounded(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = 12
        return original(self, method, url, **kwargs)

    requests.sessions.Session.request = bounded
    import pandas as pd

    if name.startswith("ak_"):
        import akshare as ak

        if name.startswith("ak_em_"):
            adjustment = name.rsplit("_", 1)[1]
            query = dict(
                symbol="000001",
                start_date="20240520",
                end_date="20240614",
                adjust="" if adjustment == "raw" else adjustment,
                timeout=12,
            )
            frame = ak.stock_zh_a_hist(**query)
        elif name.startswith("ak_tx_"):
            adjustment = name.rsplit("_", 1)[1]
            query = dict(
                symbol="sz000001",
                start_date="20240520",
                end_date="20240614",
                adjust="" if adjustment == "raw" else adjustment,
                timeout=12,
            )
            frame = ak.stock_zh_a_hist_tx(**query)
        elif name == "ak_financial_sina":
            query = dict(symbol="000001")
            frame = ak.stock_financial_abstract(**query)
        elif name == "ak_financial":
            query = dict(symbol="SZ000001")
            frame = ak.stock_profit_sheet_by_report_em(**query)
        else:
            query = dict(symbol="000001")
            frame = ak.stock_value_em(**query)
    else:
        import baostock as bs

        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"login {login.error_code}: {login.error_msg}")
        try:
            if name == "bao_profit":
                query = dict(code="sz.000001", year=2024, quarter=1)
                result = bs.query_profit_data(**query)
            elif name == "bao_factors":
                query = dict(code="sz.000001", start_date="2024-05-20", end_date="2024-06-14")
                result = bs.query_adjust_factor(**query)
            else:
                query = dict(
                    code="sz.000001",
                    start_date="2024-05-20",
                    end_date="2024-06-14",
                    frequency="d",
                    adjustflag={"raw": "3", "qfq": "2", "hfq": "1"}[name[4:]],
                )
                result = bs.query_history_k_data_plus(
                    fields="date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST",
                    **query,
                )
            if result.error_code != "0":
                raise RuntimeError(f"query {result.error_code}: {result.error_msg}")
            rows = []
            while result.next():
                rows.append(result.get_row_data())
            frame = pd.DataFrame(rows, columns=result.fields)
        finally:
            bs.logout()
    if frame.empty:
        return dict(status="EMPTY", query=query, columns=list(frame.columns), rows=0)
    OUT.mkdir(exist_ok=True)
    # Natural outputs of this spike, not edits to application files.
    path = OUT / f"{name}.parquet"
    frame.to_parquet(path, index=False)
    import duckdb

    with duckdb.connect(":memory:") as con:
        count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    sample = pd.concat([frame.head(2), frame.tail(2)]).drop_duplicates()
    return dict(
        status="OK",
        query=query,
        rows=len(frame),
        columns=list(frame.columns),
        dtypes={str(k): str(v) for k, v in frame.dtypes.items()},
        sample=json.loads(sample.to_json(orient="records", date_format="iso", force_ascii=False)),
        parquet_file=path.name,
        parquet_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        duckdb_rows=count,
    )


def run_case(name):
    started = utc()
    tick = time.monotonic()
    try:
        p = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=55,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines = [line for line in p.stdout.splitlines() if line.startswith(MARKER)]
        payload = (
            json.loads(lines[-1][len(MARKER) :])
            if lines
            else {"status": "PROCESS_ERROR", "error": p.stderr[-1400:], "exit_code": p.returncode}
        )
    except subprocess.TimeoutExpired:
        payload = dict(status="TIMEOUT", error="Child exceeded 55s including import time")
    return dict(
        case=name,
        started_at=started,
        finished_at=utc(),
        elapsed_seconds=round(time.monotonic() - tick, 3),
        **payload,
    )


def main():
    OUT.mkdir(exist_ok=True)
    versions = {
        name: importlib.metadata.version(name)
        for name in ["akshare", "baostock", "pandas", "numpy", "duckdb", "pyarrow", "requests"]
    }
    results = dict(started_at=utc(), python=sys.version, versions=versions, probes=[])
    # At most two calls at once; no retries and no full-market scans.
    recheck = "--recheck" in sys.argv
    cases = ["ak_em_raw", "bao_qfq", "ak_financial_sina"] if recheck else CASES
    filename = "recheck.json" if recheck else "summary.json"
    with concurrent.futures.ThreadPoolExecutor(max_workers=1 if recheck else 2) as pool:
        for row in pool.map(run_case, cases):
            results["probes"].append(row)
            (OUT / filename).write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"{row['case']}: {row['status']} rows={row.get('rows', 0)} "
                f"elapsed={row['elapsed_seconds']}s",
                flush=True,
            )
    results["finished_at"] = utc()
    (OUT / filename).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        try:
            output = probe(sys.argv[2])
        except Exception as exc:
            output = dict(status="ERROR", error_type=type(exc).__name__, error=str(exc)[:1800])
        print(MARKER + json.dumps(output, ensure_ascii=False, default=str), flush=True)
    else:
        main()
