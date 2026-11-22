"""Step 6. The scale-free snapshot at a decision clock.

Prices stay out. The raw footprint string is not an input. The memory
summary is not here. A bar whose close is after the clock is not read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from Model.clock import decision_clock
from Model.higher import build_series
from Model.load import Bar, FootprintLevel
from Model.predict import load_frozen_model, predict_probability
from Model.score import features_for, true_range_and_atr
from Model.zones import Zone


SESSION_MINUTES = 6 * 60 + 15


@dataclass(frozen=True)
class FootprintSummary:
    delta_over_volume: float | None
    poc_location: float | None
    lower_third_buy_share: float | None
    upper_third_buy_share: float | None
    imbalance_share: float | None


@dataclass(frozen=True)
class TimeframeContext:
    close_ema20_over_atr: float | None
    ema_gap_over_atr: float | None
    true_range_over_atr: float | None
    volume_over_average: float | None


@dataclass(frozen=True)
class PositionState:
    """A later step can fill this. The first decision is flat, with no trade."""

    state: str = "flat"
    unrealized_r: float | None = None
    bars_since_signal: int | None = None
    bars_in_trade: int | None = None
    stop_distance: float | None = None
    target_distance: float | None = None
    equity_over_start: float | None = None
    unrealized_rupee_over_equity: float | None = None
    stop_fraction_of_equity: float | None = None
    retest: Bar | None = None


@dataclass(frozen=True)
class Snapshot:
    features: tuple[float, ...]
    p_accept: float
    leg_in_body_pct: float
    leg_in_upper_wick_pct: float
    leg_in_lower_wick_pct: float
    uoc_body_pct: float
    uoc_upper_wick_pct: float
    uoc_lower_wick_pct: float
    leg_out_body_pct: float
    leg_out_upper_wick_pct: float
    leg_out_lower_wick_pct: float
    close_ema20_over_atr: float | None
    ema_gap_over_atr: float | None
    zone_height_over_atr: float | None
    datr_over_atr: float | None
    order_state: str
    unrealized_r: float | None
    bars_since_signal: int | None
    bars_in_trade: int | None
    distance_to_stop: float | None
    distance_to_target: float | None
    equity_over_start: float | None
    unrealized_rupee_over_equity: float | None
    stop_fraction_of_equity: float | None
    base_footprint: FootprintSummary
    leg_out_footprint: FootprintSummary
    retest_footprint: FootprintSummary | None
    daily: TimeframeContext
    weekly: TimeframeContext
    monthly: TimeframeContext


def snapshot_at(
    bars: Sequence[Bar],
    zone: Zone,
    clock: datetime | None = None,
    position: PositionState | None = None,
) -> Snapshot:
    """The inputs knowable at the close of the zone's last candle."""
    signal = bars[zone.end]
    base = bars[zone.start + 1]
    leg_in = bars[zone.start]
    leg_out = bars[zone.end]
    at = clock or decision_clock(signal)
    true_range, atr = true_range_and_atr(bars)
    features = tuple(features_for(bars, zone, true_range, atr))
    held = position or PositionState()
    atr_14 = signal.atr_14
    return Snapshot(
        features=features,
        p_accept=predict_probability(load_frozen_model(), list(features)),
        leg_in_body_pct=_wick_pct(leg_in, "body"),
        leg_in_upper_wick_pct=_wick_pct(leg_in, "upper"),
        leg_in_lower_wick_pct=_wick_pct(leg_in, "lower"),
        uoc_body_pct=_wick_pct(base, "body"),
        uoc_upper_wick_pct=_wick_pct(base, "upper"),
        uoc_lower_wick_pct=_wick_pct(base, "lower"),
        leg_out_body_pct=_wick_pct(leg_out, "body"),
        leg_out_upper_wick_pct=_wick_pct(leg_out, "upper"),
        leg_out_lower_wick_pct=_wick_pct(leg_out, "lower"),
        close_ema20_over_atr=_over(None if signal.ema_20 is None else signal.close - signal.ema_20, atr_14),
        ema_gap_over_atr=_over(
            None if signal.ema_20 is None or signal.ema_50 is None else signal.ema_20 - signal.ema_50,
            atr_14,
        ),
        zone_height_over_atr=_over(zone.uoc_high - zone.uoc_low, atr_14),
        datr_over_atr=_over(signal.datr_14, atr_14),
        order_state=held.state,
        unrealized_r=held.unrealized_r,
        bars_since_signal=held.bars_since_signal,
        bars_in_trade=held.bars_in_trade,
        distance_to_stop=_over(held.stop_distance, atr_14),
        distance_to_target=_over(held.target_distance, atr_14),
        equity_over_start=held.equity_over_start,
        unrealized_rupee_over_equity=held.unrealized_rupee_over_equity,
        stop_fraction_of_equity=held.stop_fraction_of_equity,
        base_footprint=footprint_summary(base),
        leg_out_footprint=footprint_summary(leg_out),
        retest_footprint=None if held.retest is None else footprint_summary(held.retest),
        daily=_context(bars, "daily", at, session_fraction(at)),
        weekly=_context(bars, "weekly", at, 1.0),
        monthly=_context(bars, "monthly", at, 1.0),
    )


def footprint_summary(bar: Bar) -> FootprintSummary:
    span = bar.high - bar.low
    levels = bar.footprint
    poc = None
    lower = None
    upper = None
    if levels and span > 0:
        total = max(level.buy + level.sell for level in levels)
        heaviest = next(level for level in levels if level.buy + level.sell == total)
        poc = (heaviest.price - bar.low) / span
        lower_cut = bar.low + span / 3
        upper_cut = bar.high - span / 3
        lower = _buy_share(level for level in levels if level.price <= lower_cut)
        upper = _buy_share(level for level in levels if level.price >= upper_cut)
    return FootprintSummary(
        delta_over_volume=(bar.delta / bar.volume) if bar.volume else None,
        poc_location=poc,
        lower_third_buy_share=lower,
        upper_third_buy_share=upper,
        imbalance_share=_imbalance(levels),
    )


def session_fraction(clock: datetime) -> float:
    """How much of the 09:15–15:30 session has elapsed at this clock."""
    if (clock.hour, clock.minute, clock.second) >= (15, 30, 0):
        return 1.0
    elapsed = (clock.hour * 60 + clock.minute + clock.second / 60) - (9 * 60 + 15)
    if elapsed <= 0:
        return 0.0
    return min(elapsed / SESSION_MINUTES, 1.0)


def _context(bars: Sequence[Bar], timeframe: str, clock: datetime, fraction: float) -> TimeframeContext:
    series = build_series(bars, timeframe, clock)
    if not series:
        return TimeframeContext(None, None, None, None)
    current = series[-1]
    atr = current.atr
    if timeframe != "daily":
        daily = build_series(bars, "daily", clock)
        atr = daily[-1].atr if daily else None
    average = current.average_volume
    volume = None
    if average not in (None, 0) and fraction:
        volume = (current.volume / fraction) / average
    return TimeframeContext(
        close_ema20_over_atr=_over(None if current.ema_20 is None else current.close - current.ema_20, atr),
        ema_gap_over_atr=_over(
            None if current.ema_20 is None or current.ema_50 is None else current.ema_20 - current.ema_50,
            atr,
        ),
        true_range_over_atr=_over(current.true_range, atr),
        volume_over_average=volume,
    )


def _wick_pct(bar: Bar, part: str) -> float:
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


def _buy_share(levels) -> float | None:
    buy = 0.0
    sell = 0.0
    for level in levels:
        buy += level.buy
        sell += level.sell
    total = buy + sell
    if total == 0:
        return None
    return buy / total


def _imbalance(levels: Sequence[FootprintLevel]) -> float | None:
    if not levels:
        return None
    flagged = 0
    for level in levels:
        if level.buy == 0 and level.sell == 0:
            continue
        if level.buy >= 3 * level.sell or level.sell >= 3 * level.buy:
            flagged += 1
    return flagged / len(levels)


def _over(value: float | None, atr: float | None) -> float | None:
    if value is None or atr is None or atr == 0 or atr != atr or value != value:
        return None
    return value / atr
