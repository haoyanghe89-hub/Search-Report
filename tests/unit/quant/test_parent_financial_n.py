from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from marketpulse.quant.compute.financials import ttm_profit, yoy_growth
from marketpulse.quant.compute.valuation import valuation_check
from marketpulse.quant.data.financial_normalize import BASIS, normalize_parent
from marketpulse.quant.data.normalize import normalize
from marketpulse.quant.domain import DataRequest, FinancialFact, PricePoint, PriceSeries


def request(dataset="financial", fields=("income_statement",)):
    return DataRequest(
        instruments=("ins_parent_fixture",),
        dataset=dataset,
        start=date(2022, 1, 1),
        end=date(2024, 6, 14),
        asof=datetime(2024, 6, 15, tzinfo=UTC),
        fields=fields,
        normalizer_version="3-parent-2",
    )


def test_parent_normalization_preserves_cumulative_period_currency_revision_and_null():
    rows, units = normalize_parent(
        [
            {
                "REPORT_DATE": "2024-03-31",
                "NOTICE_DATE": "2024-04-20",
                "UPDATE_DATE": "2025-04-20",
                "CURRENCY": "CNY",
                "PARENT_NETPROFIT": 30,
                "OPERATE_INCOME": None,
            },
            {"REPORT_DATE": "2024-06-30", "NOTICE_DATE": "2024-08-20", "CURRENCY": "CNY"},
        ],
        request(),
        "ins_parent_fixture",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["period_basis"] == "ytd"
    assert row["period_start"] == "2024-01-01"
    assert row["parent_net_profit"] == "30"
    assert row["revenue"] is None
    assert row["revision"] == "2025-04-20"
    assert row["metric_basis"]["revenue"] == "consolidated"
    assert row["share_basis"] == BASIS
    assert dict(units)["parent_net_profit"] == "CNY"


def test_parent_currency_never_inferred():
    with pytest.raises(ValueError, match="CNY"):
        normalize_parent(
            [{"REPORT_DATE": "2024-03-31", "NOTICE_DATE": "2024-04-20"}],
            request(),
            "ins_parent_fixture",
        )


def fact(metric, end, value, basis="point", start=None, statement="parent", unit="CNY"):
    return FinancialFact(
        metric=metric,
        period_end=end,
        period_start=start,
        value=value,
        unit=unit,
        available_at=datetime(2024, 4, 23, tzinfo=UTC),
        statement_basis=statement,
        period_basis=basis,
        share_basis=BASIS,
        source_hash="frozen-test",
    )


def test_ttm_cumulative_and_roe_use_real_beginning_equity():
    facts = (
        fact("parent_net_profit", date(2023, 12, 31), 100, "annual"),
        fact("parent_net_profit", date(2023, 3, 31), 20, "ytd"),
        fact("parent_net_profit", date(2024, 3, 31), 30, "ytd"),
        fact("parent_equity", date(2023, 3, 31), 200),
        fact("parent_equity", date(2024, 3, 31), 240),
        fact("total_shares", date(2024, 6, 14), 100, unit="share"),
    )
    assert ttm_profit(facts).value == 110
    assert ttm_profit(facts).period_start == date(2023, 4, 1)
    series = PriceSeries(
        instrument_id="ins_parent_fixture",
        currency="CNY",
        adjustment="raw",
        points=(PricePoint(session_date=date(2024, 6, 14), close=10),),
    )
    values = {
        v.name: v for v in valuation_check(series=series, financials=facts, asof=request().asof)
    }
    assert values["roe"].value == Decimal("0.5")
    assert abs(values["pe"].value - Decimal(100) / 11) < Decimal("1e-25")
    assert abs(values["pb"].value - Decimal(25) / 6) < Decimal("1e-25")
    without_begin = tuple(
        f for f in facts if not (f.metric == "parent_equity" and f.period_end.year == 2023)
    )
    assert (
        next(
            v
            for v in valuation_check(series=series, financials=without_begin, asof=request().asof)
            if v.name == "roe"
        ).value
        is None
    )


def test_revenue_growth_is_consolidated_not_mislabelled_parent():
    facts = (
        fact("revenue", date(2023, 3, 31), 100, "ytd", statement="consolidated"),
        fact("revenue", date(2024, 3, 31), 110, "ytd", statement="consolidated"),
    )
    assert yoy_growth(facts, "revenue") == (Decimal("0.1"), None)
    wrong = tuple(f.model_copy(update={"metric": "parent_net_profit"}) for f in facts)
    assert ttm_profit(wrong) is None


def test_historical_shares_have_close_label_not_fictional_announcement():
    rows, units = normalize(
        [{"数据日期": "2024-06-14", "总股本": 100, "流通股本": 80}],
        request("valuation", ("total_shares",)),
        "akshare_eastmoney",
        "ins_parent_fixture",
    )
    assert rows[0]["published_at"] is None
    assert rows[0]["available_at"] == "2024-06-14T15:00:00+08:00"
    assert "not_first_seen" in rows[0]["availability_basis"]
    assert dict(units)["total_shares"] == "share"
