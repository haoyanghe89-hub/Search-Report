from datetime import date
from decimal import Decimal

from marketpulse.quant.compute.exhibits import price_cells
from marketpulse.quant.domain import MetricSpec, PricePoint, PriceSeries
from tests.unit.quant.test_contracts_data import ID


def test_exhibits_preserve_raw_values_and_drawdown_cells():
    series = PriceSeries(
        instrument_id=ID,
        currency="CNY",
        adjustment="raw",
        points=tuple(
            PricePoint(session_date=date(2024, 6, d), close=Decimal(v))
            for d, v in [(12, "100"), (13, "110"), (14, "99")]
        ),
    )
    cells = price_cells(series, MetricSpec())
    assert [v.value for v in cells if v.name == "chart_price_raw"] == list(
        map(Decimal, [100, 110, 99])
    )
    assert [v.value for v in cells if v.name == "chart_drawdown_raw"] == [
        Decimal(0),
        Decimal(0),
        Decimal("-0.1"),
    ]
    assert all(v.start == v.end and len(v.row_keys) == 1 for v in cells)
