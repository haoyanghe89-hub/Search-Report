from decimal import Decimal, localcontext

from ..domain import MetricSpec, PriceSeries
from .metrics import metric, prices


def _ema(values, window):
    result, current, buffer = [], None, []
    alpha = Decimal(2) / (window + 1)
    for value in values:
        if value is None:
            current, buffer = None, []
        elif current is None:
            buffer.append(value)
            if len(buffer) == window:
                current = sum(buffer) / window
        else:
            current += alpha * (value - current)
        result.append(current)
    return result


def compute_indicators(*, series: PriceSeries, spec: MetricSpec):
    with localcontext() as context:
        context.prec = 40
        ps = prices(series, spec)
        sma = []
        for i in range(len(ps)):
            window = ps[max(0, i - spec.sma_window + 1) : i + 1]
            sma.append(
                sum(window) / len(window)
                if len(window) == spec.sma_window and None not in window
                else None
            )
        ema = _ema(ps, spec.ema_window)
        fast, slow, signal_window = spec.macd_windows
        macd = [
            a - b if a is not None and b is not None else None
            for a, b in zip(_ema(ps, fast), _ema(ps, slow), strict=False)
        ]
        signal = _ema(macd, signal_window)
        histogram = [
            a - b if a is not None and b is not None else None
            for a, b in zip(macd, signal, strict=False)
        ]
        rsi, gains, losses, avg_gain, avg_loss = [], [], [], None, None
        for i, p in enumerate(ps):
            if i == 0 or p is None or ps[i - 1] is None:
                gains, losses, avg_gain, avg_loss = [], [], None, None
                rsi.append(None)
                continue
            change = p - ps[i - 1]
            gain, loss = max(change, Decimal(0)), max(-change, Decimal(0))
            if avg_gain is None:
                gains.append(gain)
                losses.append(loss)
                if len(gains) == spec.rsi_window:
                    avg_gain, avg_loss = sum(gains) / spec.rsi_window, sum(losses) / spec.rsi_window
            else:
                avg_gain = (avg_gain * (spec.rsi_window - 1) + gain) / spec.rsi_window
                avg_loss = (avg_loss * (spec.rsi_window - 1) + loss) / spec.rsi_window
            value = (
                None
                if avg_gain is None or avg_gain + avg_loss == 0
                else 100 * avg_gain / (avg_gain + avg_loss)
            )
            rsi.append(value)
        outputs = []
        for name, values, definition, unit in (
            ("sma", sma, f"SMA{spec.sma_window};full_window;reset_on_missing", "CNY/share"),
            (
                "ema",
                ema,
                f"EMA{spec.ema_window};SMA_seed;alpha=2/(n+1);reset_on_missing",
                "CNY/share",
            ),
            (
                "rsi",
                rsi,
                f"Wilder_RSI{spec.rsi_window};n_changes_seed;flat=null;reset_on_missing",
                "index_0_100",
            ),
            ("macd", macd, f"EMA{fast}-EMA{slow};SMA_seed", "CNY/share"),
            ("macd_signal", signal, f"EMA{signal_window}(MACD);SMA_seed", "CNY/share"),
            ("macd_histogram", histogram, "MACD-signal;no_x2", "CNY/share"),
        ):
            for p, value in zip(series.points, values, strict=False):
                outputs.append(
                    metric(
                        series,
                        name,
                        value,
                        unit,
                        definition + ";auxiliary_only",
                        reason="warmup_missing_or_flat" if value is None else None,
                        row_keys=(p.session_date.isoformat(),),
                    )
                )
        return tuple(outputs)
