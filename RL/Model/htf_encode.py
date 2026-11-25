"""Plan 2 §3. Truncated daily / weekly / monthly windows as scale-free features.

Each higher-timeframe bar is encoded the same way: ATR distances, volume
ratio, and wick percentages. Raw rupee prices stay out. Window lengths are
fixed before the first training run. A bar whose close is after the decision
clock is never read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from Model.higher import PeriodBar, build_series
from Model.load import Bar
from Model.snapshot import session_fraction


# Locked before the first Plan 2 training run. Do not tune on 2024+.
DAILY_WINDOW = 20
WEEKLY_WINDOW = 12
MONTHLY_WINDOW = 12

BAR_KEYS = (
    "close_ema20_over_atr",
    "ema_gap_over_atr",
    "true_range_over_atr",
    "volume_over_average",
    "body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "is_partial",
)

WINDOWS = (
    ("daily", DAILY_WINDOW),
    ("weekly", WEEKLY_WINDOW),
    ("monthly", MONTHLY_WINDOW),
)


def htf_width() -> int:
    """Total floats in the truncated HTF block."""
    return sum(length * len(BAR_KEYS) for _, length in WINDOWS)


def htf_feature_names() -> tuple[str, ...]:
    """Frozen column names for the HTF block, left-padded oldest first."""
    names: list[str] = []
    for timeframe, length in WINDOWS:
        for index in range(length):
            for key in BAR_KEYS:
                names.append(f"htf_{timeframe}_{index}_{key}")
    return tuple(names)


def encode_htf(bars: Sequence[Bar], clock: datetime) -> tuple[float | None, ...]:
    """Daily, weekly, and monthly truncated windows knowable at `clock`."""
    values: list[float | None] = []
    daily_atr = _daily_atr(bars, clock)
    fraction = session_fraction(clock)
    for timeframe, length in WINDOWS:
        series = build_series(bars, timeframe, clock)
        window = series[-length:] if series else []
        pad = length - len(window)
        for _ in range(pad):
            values.extend((None,) * len(BAR_KEYS))
        for bar in window:
            atr = daily_atr if timeframe != "daily" else bar.atr
            vol_fraction = fraction if timeframe == "daily" else 1.0
            values.extend(_encode_bar(bar, atr, vol_fraction))
    return tuple(values)


def _encode_bar(
    bar: PeriodBar,
    atr: float | None,
    volume_fraction: float,
) -> tuple[float | None, ...]:
    average = bar.average_volume
    volume = None
    if average not in (None, 0) and volume_fraction:
        volume = (bar.volume / volume_fraction) / average
    return (
        _over(None if bar.ema_20 is None else bar.close - bar.ema_20, atr),
        _over(
            None if bar.ema_20 is None or bar.ema_50 is None else bar.ema_20 - bar.ema_50,
            atr,
        ),
        _over(bar.true_range, atr),
        volume,
        _wick_pct(bar, "body"),
        _wick_pct(bar, "upper"),
        _wick_pct(bar, "lower"),
        1.0 if bar.partial else 0.0,
    )


def _daily_atr(bars: Sequence[Bar], clock: datetime) -> float | None:
    daily = build_series(bars, "daily", clock)
    if not daily:
        return None
    return daily[-1].atr


def _wick_pct(bar: PeriodBar, part: str) -> float:
    span = bar.high - bar.low
    if span <= 0:
        return 0.0
    if part == "body":
        value = abs(bar.close - bar.open)
    elif part == "upper":
        value = bar.high - max(bar.open, bar.close)
    else:
        value = min(bar.open, bar.close) - bar.low
    return (value / span) * 100


def _over(value: float | None, atr: float | None) -> float | None:
    if value is None or atr is None or atr == 0 or atr != atr or value != value:
        return None
    return value / atr
