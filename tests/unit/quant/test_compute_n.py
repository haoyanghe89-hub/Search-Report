from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from marketpulse.quant.compute.metrics import compute_metrics
from marketpulse.quant.compute.valuation import valuation_check
from marketpulse.quant.contracts import MetricSpec, PricePoint, PriceSeries


def series(prices, adjustment="raw"):
    return PriceSeries(
        instrument_id="ins_fixture000",
        currency="CNY",
        adjustment=adjustment,
        points=tuple(
            PricePoint(session_date=date(2024, 1, i + 2), close=p) for i, p in enumerate(prices)
        ),
    )


def test_hand_calculated_return_drawdown_and_unrecovered():
    values = {v.name: v for v in compute_metrics(series=series([100, 110, 99]), spec=MetricSpec())}
    assert values["return"].value == Decimal("-0.01")
    assert values["drawdown"].value == Decimal("-0.1")
    assert values["drawdown"].recovery_date is None
    first = compute_metrics(series=series([100, 110, 99]), spec=MetricSpec())[0]
    assert first.value is None
    assert first.missing_reason == "first_observation"


def test_null_is_not_dropped_or_zero():
    values = compute_metrics(series=series([100, None, 99]), spec=MetricSpec())
    assert next(v for v in values if v.name == "return").value is None


def test_valuation_missing_is_not_invented():
    values = valuation_check(
        series=series([100, 110]), financials=(), asof=datetime(2024, 1, 4, tzinfo=UTC)
    )
    assert all(v.value is None and v.missing_reason for v in values)


def test_aware_and_frozen_contract():
    with pytest.raises(ValueError):
        PriceSeries(
            instrument_id="ins_fixture000",
            currency="CNY",
            adjustment="raw",
            points=series([100]).points,
            asof=datetime(2024, 1, 2),
        )


def test_incomplete_session_and_overwide_tolerance_rejected():
    with pytest.raises(ValueError, match="incomplete session"):
        PriceSeries(
            instrument_id="ins_fixture000",
            currency="CNY",
            adjustment="raw",
            points=series([100]).points,
            asof=datetime(2024, 1, 2, 6, tzinfo=UTC),
        )
    for field, value in [("absolute_tolerance", "1e-9"), ("relative_tolerance", "1e-7")]:
        with pytest.raises(ValueError):
            MetricSpec(**{field: value})
