"""Offline integrity and field checks for real spike outputs, not a backtest."""

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent / "results"
reports = [json.loads((ROOT / "summary.json").read_text(encoding="utf-8"))]
if (ROOT / "recheck.json").exists():
    reports.append(json.loads((ROOT / "recheck.json").read_text(encoding="utf-8")))
checks = []
for report in reports:
    for probe in report["probes"]:
        if probe["status"] != "OK":
            continue
        path = ROOT / probe["parquet_file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == probe["parquet_sha256"]
        with duckdb.connect(":memory:") as con:
            assert (
                con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
                == probe["rows"]
            )
        checks.append(probe["case"])
raw_bao = pd.read_parquet(ROOT / "bao_raw.parquet")
raw_tx = pd.read_parquet(ROOT / "ak_tx_raw.parquet")
assert len(raw_bao) == len(raw_tx) == 19
assert raw_bao.date.is_unique and raw_tx.date.is_unique
assert raw_bao.date.is_monotonic_increasing and raw_tx.date.is_monotonic_increasing
joined = raw_bao.assign(date=pd.to_datetime(raw_bao.date)).merge(
    raw_tx.assign(date=pd.to_datetime(raw_tx.date)), on="date", suffixes=("_bao", "_tx")
)
close_error = (joined.close_bao.astype(float) - joined.close_tx).abs().max()
assert close_error <= 0.01
volume_ratio = (joined.volume_bao.astype(float) / joined.volume_tx).median()
turn_ratio = (joined.turn.astype(float) / joined.turnover).median()
profit = pd.read_parquet(ROOT / "bao_profit.parquet")
assert {"pubDate", "statDate", "netProfit", "epsTTM"} <= set(profit.columns)
assert profit.pubDate.iloc[0] >= profit.statDate.iloc[0]
assert profit.gpMargin.iloc[0] == "" and profit.MBRevenue.iloc[0] == ""
qfq_em = pd.read_parquet(ROOT / "ak_em_qfq.parquet")
qfq_tx = pd.read_parquet(ROOT / "ak_tx_qfq.parquet")
qjoin = qfq_em.assign(date=pd.to_datetime(qfq_em["日期"])).merge(
    qfq_tx.assign(date=pd.to_datetime(qfq_tx.date)), on="date"
)
summary = dict(
    verified_artifacts=len(checks),
    cases=checks,
    rows_compared=len(joined),
    max_raw_close_error=float(close_error),
    median_bao_vs_tx_volume_ratio=float(volume_ratio),
    median_bao_turn_percent_vs_tx_turnover_fraction=float(turn_ratio),
    max_em_vs_tx_qfq_close_difference=float((qjoin["收盘"] - qjoin.close).abs().max()),
    profit_pubDate=profit.pubDate.iloc[0],
    profit_statDate=profit.statDate.iloc[0],
    missing_bank_fields=["gpMargin", "MBRevenue"],
    note="19 historical days, one stock; not SLA, PIT completeness, independence or backtest proof",
)
(ROOT / "offline_checks.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
