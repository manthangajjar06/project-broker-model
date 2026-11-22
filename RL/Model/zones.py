"""Step 3. Zone geometry, ported from the chart.

`single_candidates` and `super_candidates` follow `RL/RL/src/model/zones.js`.
The base candle is the UOC. Its low and its high are the zone. The fresh-or-worked
walk in `buildZone` is not used. Probability is not used to drop a zone here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from Model.load import Bar


@dataclass(frozen=True)
class ZoneMetrics:
    leg_in_body: float
    boring_body: float
    boring_ratio_pct: float
    boring_color: str
    has_gap: bool
    gap_size: float
    adjusted_leg_out_body: float
    penetration_pct: float | None
    rally_candle_count: int


@dataclass(frozen=True)
class Zone:
    pattern: str
    leg_out_mode: str
    start: int
    end: int
    uoc_low: float
    uoc_high: float
    metrics: ZoneMetrics


def _body(bar: Bar) -> float:
    return abs(bar.close - bar.open)


def _is_red(bar: Bar) -> bool:
    if bar.close >= bar.open:
        return False
    span = bar.high - bar.low
    return span > 0 and (bar.open - bar.close) / span >= 0.55


def _is_green(bar: Bar) -> bool:
    if bar.close <= bar.open:
        return False
    span = bar.high - bar.low
    return span > 0 and (bar.close - bar.open) / span >= 0.55


def _is_boring(bar: Bar, leg_body: float) -> bool:
    return _body(bar) < 0.45 * leg_body


def _gap(boring_top: float, boring_body: float, leg_out_open: float) -> dict:
    has_gap = leg_out_open > boring_top
    overlap = max(0.0, boring_top - leg_out_open)
    return {
        "has_gap": has_gap,
        "effective_open": boring_top if has_gap else leg_out_open,
        "gap_size": max(0.0, leg_out_open - boring_top),
        "penetration_pct": (overlap / boring_body) * 100 if boring_body > 0 else None,
    }


def _js_round(value: float, digits: int) -> float:
    """Math.round: a tie at .5 goes toward +infinity."""
    factor = 10 ** digits
    scaled = value * factor
    whole = math.floor(scaled)
    fraction = scaled - whole
    if fraction > 0.5 or fraction == 0.5:
        whole += 1
    return whole / factor


def _metrics(gap: dict, leg_body: float, base_body: float, boring_green: bool, adjusted: float, rally_count: int) -> ZoneMetrics:
    penetration = gap["penetration_pct"]
    return ZoneMetrics(
        leg_in_body=_js_round(leg_body, 2),
        boring_body=_js_round(base_body, 2),
        boring_ratio_pct=_js_round((base_body / leg_body) * 100 if leg_body else 0.0, 1),
        boring_color="Green" if boring_green else "Red",
        has_gap=gap["has_gap"],
        gap_size=_js_round(gap["gap_size"], 2),
        adjusted_leg_out_body=_js_round(adjusted, 2),
        penetration_pct=None if penetration is None else _js_round(penetration, 1),
        rally_candle_count=rally_count,
    )


def _zone(kind: str, mode: str, start: int, end: int, bars: Sequence[Bar], metrics: ZoneMetrics) -> Zone:
    base = bars[start + 1]
    return Zone(kind, "SUPER" if "SUPER" in mode else "SINGLE", start, end, base.low, base.high, metrics)


def single_candidates(bars: Sequence[Bar]) -> list[Zone]:
    found: list[Zone] = []
    for index in range(len(bars) - 2):
        leg = bars[index]
        base = bars[index + 1]
        out = bars[index + 2]
        setups = []
        if _is_red(leg):
            setups.append("DBR")
        if _is_green(leg):
            setups.append("RBR")
        for kind in setups:
            if leg.date != base.date:
                continue
            leg_body = leg.open - leg.close if kind == "DBR" else leg.close - leg.open
            if not _is_boring(base, leg_body):
                continue
            if out.close <= out.open:
                continue
            raw_body = out.close - out.open
            raw_range = out.high - out.low
            if raw_range <= 0 or raw_body < raw_range - raw_body:
                continue
            if kind == "DBR" and out.open > leg.open:
                continue
            if out.open < base.low:
                continue
            base_body = _body(base)
            boring_green = base.close >= base.open
            boring_top = base.close if boring_green else base.open
            gap = _gap(boring_top, base_body, out.open)
            if not (raw_range > 0 and raw_body / raw_range >= 0.55):
                continue
            adjusted = out.close - gap["effective_open"]
            if not (adjusted > leg_body and adjusted > base_body):
                continue
            found.append(_zone(kind, "SINGLE (1 Candle)", index, index + 2, bars, _metrics(
                gap, leg_body, base_body, boring_green, adjusted, 1,
            )))
    return found


def super_candidates(bars: Sequence[Bar]) -> list[Zone]:
    found: list[Zone] = []
    for index in range(len(bars) - 4):
        one = bars[index]
        base = bars[index + 1]
        three = bars[index + 2]
        four = bars[index + 3]
        five = bars[index + 4]
        setups = []
        if _is_red(one):
            setups.append("DBR")
        if _is_green(one):
            setups.append("RBR")
        for kind in setups:
            if one.date != base.date:
                continue
            leg_body = abs(one.close - one.open)
            if not _is_boring(base, leg_body) or three.close <= three.open:
                continue
            raw_body = three.close - three.open
            raw_range = three.high - three.low
            if raw_range <= 0 or raw_body < raw_range - raw_body or three.open < base.low:
                continue
            if kind == "DBR" and three.open > one.open:
                continue
            if four.close < four.open or five.close < five.open:
                continue
            if not (four.close > four.open or five.close > five.open):
                continue
            base_body = _body(base)
            boring_green = base.close >= base.open
            base_top = base.close if boring_green else base.open
            gap = _gap(base_top, base_body, three.open)
            super_body = five.close - gap["effective_open"]
            super_range = max(three.high, four.high, five.high) - min(
                three.low, four.low, five.low, gap["effective_open"],
            )
            super_wick = super_range - super_body
            if not (super_body > super_wick and super_body > leg_body and super_body > base_body):
                continue
            found.append(_zone(kind, "SUPER (3 Candles)", index, index + 4, bars, _metrics(
                gap, leg_body, base_body, boring_green, super_body, 3,
            )))
    return found


def find_zones(bars: Sequence[Bar]) -> list[Zone]:
    """Every geometric zone, one copy of each pattern, start, end, and mode.

    This is the chart's candidate list before a probability chooses among zones
    that share a pattern and a start.
    """
    seen: set[tuple[str, int, int, str]] = set()
    zones: list[Zone] = []
    for zone in [*single_candidates(bars), *super_candidates(bars)]:
        key = (zone.pattern, zone.start, zone.end, zone.leg_out_mode)
        if key in seen:
            continue
        seen.add(key)
        zones.append(zone)
    return zones


def keep_one(zones: Sequence[Zone], probabilities: Sequence[float]) -> list[Zone]:
    """One zone per pattern and start. Higher probability wins. SUPER wins a tie.

    This is `markersFrom` in `zonePrimitive.js`. Step 3 does not call it on
    Reliance, because the probability is not available yet.
    """
    if len(zones) != len(probabilities):
        raise ValueError("each zone needs one probability")
    chosen: dict[tuple[str, int], int] = {}
    order: list[tuple[str, int]] = []
    for index, zone in enumerate(zones):
        key = (zone.pattern, zone.start)
        current = chosen.get(key)
        if current is None:
            chosen[key] = index
            order.append(key)
            continue
        if probabilities[index] > probabilities[current] or (
            probabilities[index] == probabilities[current] and zone.leg_out_mode == "SUPER"
        ):
            chosen[key] = index
    return [zones[chosen[key]] for key in order]
