from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pytest

from marketpulse.quant.compute.financials import ttm_profit, yoy_growth
from marketpulse.quant.compute.indicators import compute_indicators
from marketpulse.quant.compute.metrics import compute_metrics
from marketpulse.quant.compute.valuation import valuation_check
from marketpulse.quant.domain import FinancialFact, MetricSpec, decimal_text
from tests.unit.quant.test_compute_n import series


def fact(metric, value, **extra):
    return FinancialFact(
        **{
            **dict(
                metric=metric,
                value=value,
                period_end=date(2023, 12, 31),
                available_at=datetime(2024, 1, 1, tzinfo=UTC),
                unit="CNY",
                share_basis="ordinary_total_v1",
                statement_basis="parent",
                period_basis="point",
                revision="annual-v1",
                source_hash="1" * 64,
            ),
            **extra,
        }
    )


def valuation_facts():
    return (
        fact("total_shares", "1000", unit="share", period_end=date(2024, 1, 4)),
        fact("parent_net_profit", "1000", period_basis="ttm", period_start=date(2023, 1, 1)),
        fact("parent_equity", "2000"),
        fact("parent_equity_begin", "1000", period_end=date(2022, 12, 31)),
    )


def test_pe_pb_roe_hand_calculated():
    values = {
        v.name: v
        for v in valuation_check(
            series=series([40, 41, 42]),
            financials=valuation_facts(),
            asof=datetime(2024, 1, 4, 23, tzinfo=UTC),
        )
    }
    assert values["pe"].value == 42
    assert values["pb"].value == 21
    assert abs(values["roe"].value - Decimal(2) / 3) < Decimal("1e-27")


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"value": Decimal(-1)}, "nonpositive_earnings"),
        ({"share_basis": "split_adjusted"}, "share_basis_mismatch"),
        ({"available_at": datetime(2025, 1, 1, tzinfo=UTC)}, "missing_valuation_inputs"),
    ],
)
def test_negative_pe_basis_and_future(change, reason):
    shares, profit, equity, beginning = valuation_facts()
    values = valuation_check(
        series=series([40, 41, 42]),
        financials=(shares, profit.model_copy(update=change), equity, beginning),
        asof=datetime(2024, 1, 4, 23, tzinfo=UTC),
    )
    assert values[0].value is None and values[0].missing_reason == reason


def test_qfq_never_multiplies_adjusted_price_by_raw_shares():
    values = valuation_check(
        series=series([40, 41, 42], adjustment="qfq"),
        financials=valuation_facts(),
        asof=datetime(2024, 1, 4, 23, tzinfo=UTC),
    )
    assert all(v.value is None for v in values[:2])


def test_ytd_ttm_does_not_sum_cumulative_quarters():
    facts = (
        fact("parent_net_profit", 120, period_basis="annual", period_end=date(2022, 12, 31)),
        fact("parent_net_profit", 20, period_basis="ytd", period_end=date(2022, 3, 31)),
        fact("parent_net_profit", 35, period_basis="ytd", period_end=date(2023, 3, 31)),
    )
    result = ttm_profit(facts)
    assert result.value == 135 and result.period_basis == "ttm"
    assert result.period_start == date(2022, 4, 1)


def test_four_discrete_quarters_and_duplicate_revision_fail_closed():
    facts = tuple(
        fact(
            "parent_net_profit",
            n,
            period_basis="quarter",
            period_end=date(2023, m, d),
            period_start=date(2023, m - 2, 1),
        )
        for n, m, d in [(10, 3, 31), (20, 6, 30), (30, 9, 30), (40, 12, 31)]
    )
    assert ttm_profit(facts).value == 100
    assert ttm_profit(facts + (facts[-1],)) is None


def test_financial_growth_comparable_and_missing():
    new = fact("revenue", 120, period_basis="annual")
    old = fact("revenue", 100, period_basis="annual", period_end=date(2022, 12, 31))
    assert yoy_growth((new, old), "revenue") == (Decimal("0.2"), None)
    assert yoy_growth((new,), "revenue")[0] is None
    assert (
        yoy_growth((new, old.model_copy(update={"share_basis": "other"})), "revenue")[1]
        == "incomparable_periods"
    )


def test_sample_volatility_cagr_and_recovery():
    values = {
        v.name: v for v in compute_metrics(series=series([100, 110, 99, 110]), spec=MetricSpec())
    }
    returns = (Decimal("0.1"), Decimal("-0.1"), Decimal(110) / 99 - 1)
    mean = sum(returns) / 3
    expected = (sum((r - mean) ** 2 for r in returns) / 2).sqrt() * Decimal(252).sqrt()
    assert abs(values["volatility"].value - expected) < Decimal("1e-25")
    assert values["drawdown"].recovery_date == date(2024, 1, 5)
    assert values["cagr"].value > 0


def test_indicator_seed_and_flat_rsi():
    spec = MetricSpec(sma_window=3, ema_window=3, rsi_window=2, macd_windows=(2, 3, 2))
    values = compute_indicators(series=series([10, 11, 12, 13]), spec=spec)
    sma = [v for v in values if v.name == "sma"]
    ema = [v for v in values if v.name == "ema"]
    assert sma[0].value is None and sma[2].value == 11
    assert ema[2].value == 11 and ema[3].value == 12
    flat = compute_indicators(series=series([10, 10, 10, 10]), spec=spec)
    assert all(v.value is None and v.missing_reason for v in flat if v.name == "rsi")


def test_decimal_canonical_encoding_not_context_sensitive():
    with localcontext() as ctx:
        ctx.prec = 3
        assert decimal_text(Decimal("123456789.120000")) == "123456789.12"
