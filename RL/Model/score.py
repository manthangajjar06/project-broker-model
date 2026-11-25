"""Step 4. Features, entry price, and the zone probability.

The ATR inside the features is the true-range path from `zones.js`. The CSV
`atr_14` column is not read. The fresh-or-worked walk is not an input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from Model.load import Bar
from Model.predict import Model, load_frozen_model, predict_probability, score_label
from Model.zones import Zone, find_zones, keep_one


EPS = 1e-9

PATTERN = {"DBR": 0, "RBR": 1}
LEG_OUT = {"SINGLE": 0, "SUPER": 1}
BORING_COLOR = {"Green": 0, "Red": 1}


@dataclass(frozen=True)
class ScoredZone:
    zone: Zone
    probability: float
    label: str
    entry: float
    entry_warning: bool


_TR_ATR_CACHE: dict[int, tuple[list[float], list[float]]] = {}
_DAILY_ATR_CACHE: dict[int, dict[str, float]] = {}


def true_range_and_atr(bars: Sequence[Bar]) -> tuple[list[float], list[float]]:
    cache_key = id(bars)
    hit = _TR_ATR_CACHE.get(cache_key)
    if hit is not None:
        return hit

    true_range = []
    for index, bar in enumerate(bars):
        span = bar.high - bar.low
        if index == 0:
            true_range.append(span)
            continue
        previous = bars[index - 1].close
        true_range.append(max(span, abs(bar.high - previous), abs(bar.low - previous)))

    atr = [0.0] * len(bars)
    length = 14
    if len(bars) >= length:
        for index in range(length - 1):
            atr[index] = sum(true_range[: index + 1]) / (index + 1)
        atr[length - 1] = sum(true_range[:length]) / length
        for index in range(length, len(bars)):
            atr[index] = (atr[index - 1] * (length - 1) + true_range[index]) / length
    else:
        for index in range(len(bars)):
            atr[index] = sum(true_range[: index + 1]) / (index + 1)

    if len(_TR_ATR_CACHE) >= 16:
        _TR_ATR_CACHE.clear()
    result = (true_range, atr)
    _TR_ATR_CACHE[cache_key] = result
    return result


def daily_atr(bars: Sequence[Bar]) -> dict[str, float]:
    cache_key = id(bars)
    hit = _DAILY_ATR_CACHE.get(cache_key)
    if hit is not None:
        return hit
    result = _daily_atr_uncached(bars)
    if len(_DAILY_ATR_CACHE) >= 16:
        _DAILY_ATR_CACHE.clear()
    _DAILY_ATR_CACHE[cache_key] = result
    return result


def _daily_atr_uncached(bars: Sequence[Bar]) -> dict[str, float]:
    days: list[dict] = []
    for bar in bars:
        last = days[-1] if days else None
        if last is None or last["date"] != bar.date:
            days.append({"date": bar.date, "high": bar.high, "low": bar.low, "close": bar.close})
            continue
        last["high"] = max(last["high"], bar.high)
        last["low"] = min(last["low"], bar.low)
        last["close"] = bar.close

    true_range = []
    for index, day in enumerate(days):
        span = day["high"] - day["low"]
        if index == 0:
            true_range.append(span)
            continue
        previous = days[index - 1]["close"]
        true_range.append(max(span, abs(day["high"] - previous), abs(day["low"] - previous)))

    alpha = 1 / 14
    smoothed: list[float | None] = []
    value = None
    for index, span in enumerate(true_range):
        value = span if value is None else value * (1 - alpha) + span * alpha
        smoothed.append(value if index >= 13 else None)

    by_date: dict[str, float] = {}
    for index in range(1, len(days)):
        previous = smoothed[index - 1]
        if previous is not None:
            by_date[days[index]["date"]] = previous
    return by_date


def entry_price(base: Bar, leg_out: Bar, datr: float | None) -> tuple[float, bool]:
    leg_open = leg_out.open
    leg_close = leg_out.close
    lower_wick = leg_out.low < min(leg_open, leg_close) - EPS
    upper_wick = base.high > max(base.open, base.close) + EPS
    overlap = max(min(leg_open, leg_close), base.low) <= min(max(leg_open, leg_close), base.high) + EPS
    if not lower_wick:
        return leg_open, False
    if not overlap:
        return base.high, False
    if not upper_wick:
        return leg_open, False
    anchor = base.open if base.close < base.open else base.close
    if datr is None or datr != datr or datr <= 0:
        return anchor, True
    return anchor + 0.1 * datr, False


def features_for(bars: Sequence[Bar], zone: Zone, true_range: Sequence[float], atr: Sequence[float]) -> list[float]:
    window = list(bars[zone.start: zone.end + 1])
    metrics = zone.metrics
    first = window[0]
    second = window[1]
    last = window[-1]
    zone_high = max(bar.high for bar in window)
    zone_low = min(bar.low for bar in window)
    zone_range = zone_high - zone_low
    zone_open = first.open
    zone_body = abs(last.close - zone_open)
    total_volume = sum(bar.volume for bar in window)
    average_volume = total_volume / len(window) if window else 0.0
    first_range = first.high - first.low
    second_range = second.high - second.low
    last_range = last.high - last.low
    rally = [_ratio(_body(bar), bar.high - bar.low) for bar in window[2:]]
    atr_start = atr[zone.start]
    atr_end = atr[zone.end]
    features = [
        float(PATTERN[zone.pattern]),
        float(LEG_OUT[zone.leg_out_mode]),
        float(BORING_COLOR[metrics.boring_color]),
        float(metrics.rally_candle_count),
        metrics.boring_ratio_pct,
        1.0 if metrics.has_gap else 0.0,
        _number(metrics.penetration_pct),
        true_range[zone.start] / atr_start if _truthy(atr_start) else float("nan"),
        true_range[zone.end] / atr_end if _truthy(atr_end) else float("nan"),
        float(len(window)),
        _ratio(zone_body, zone_range),
        _body(last) / last_range if last_range > 0 else 0.0,
        (last.high - max(last.open, last.close)) / last_range if last_range > 0 else 0.0,
        (min(last.open, last.close) - last.low) / last_range if last_range > 0 else 0.0,
        (last.close - last.low) / last_range if last_range > 0 else 0.5,
        (last.volume / average_volume) if average_volume > 0 else 1.0,
        min(rally) if rally else 0.0,
        (first_range - _body(first)) / first_range if first_range > 0 else 0.0,
        (first.close - first.low) / first_range if first_range > 0 else 0.5,
        (second_range - _body(second)) / second_range if second_range > 0 else 0.0,
        (zone_high - zone_low) / zone_open if _truthy(zone_open) else float("nan"),
        metrics.leg_in_body / zone_open if _truthy(zone_open) else float("nan"),
        metrics.gap_size / zone_open if _truthy(zone_open) else float("nan"),
        metrics.adjusted_leg_out_body / zone_open if _truthy(zone_open) else float("nan"),
        last.volume / total_volume if total_volume > 0 else 1 / len(window),
        float(int(last.time[:2])),
        float(_weekday(last.date)),
        atr_end / atr_start if _truthy(atr_start) else float("nan"),
        metrics.boring_body / metrics.leg_in_body if _truthy(metrics.leg_in_body) else float("nan"),
        (
            metrics.adjusted_leg_out_body / (metrics.leg_in_body + metrics.boring_body)
            if _truthy(metrics.leg_in_body + metrics.boring_body)
            else float("nan")
        ),
        metrics.adjusted_leg_out_body / metrics.leg_in_body if _truthy(metrics.leg_in_body) else float("nan"),
    ]
    if len(features) != 31:
        raise ValueError(f"a zone must have 31 features, this one has {len(features)}")
    return features


def score_zones(bars: Sequence[Bar], model: Model | None = None) -> list[ScoredZone]:
    """Score every geometric zone. The CSV ATR column is not an input."""
    if len(bars) < 3:
        return []
    forest = model or load_frozen_model()
    true_range, atr = true_range_and_atr(bars)
    datr_by_date = daily_atr(bars)
    scored = []
    for zone in find_zones(bars):
        probability = predict_probability(forest, features_for(bars, zone, true_range, atr))
        base = bars[zone.start + 1]
        leg_out = bars[zone.start + 2]
        entry, warning = entry_price(base, leg_out, datr_by_date.get(base.date))
        scored.append(ScoredZone(zone, probability, score_label(probability), entry, warning))
    return scored


def accepted_zones(scored: Sequence[ScoredZone]) -> list[ScoredZone]:
    """The chart's one-zone-per-base set, kept only where the label is accepted.

    Later steps act on this list. Rejected and uncertain zones are not actions.
    """
    kept = keep_one([item.zone for item in scored], [item.probability for item in scored])
    by_identity = {id(item.zone): item for item in scored}
    return [by_identity[id(zone)] for zone in kept if by_identity[id(zone)].label == "accepted"]


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def _ratio(part: float, whole: float) -> float:
    if not _truthy(whole):
        return 0.0
    return part / whole


def _truthy(value: float) -> bool:
    return value == value and value != 0.0


def _number(value: float | None) -> float:
    if value is None or value != value:
        return float("nan")
    return value


def _weekday(iso: str) -> int:
    year, month, day = (int(part) for part in iso.split("-"))
    return date(year, month, day).weekday()
