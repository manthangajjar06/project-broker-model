"""Step 7. The one entry, stop, and target.

This file says the same thing as §15 of the implementation plan.
It reads the leg-in, the UOC, and the leg-out. Those candles have closed.
It does not read a candle after the day being decided.

Entry is allowed on accepted zones only, and only on the 6th session
or later. The zone's last candle is day 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from Model.load import Bar
from Model.predict import ACCEPT_AT
from Model.zones import Zone


# A price match closer than this is the same price.
# A wick closer than this is not a wick. The chart uses the same gap.
PRICE_GAP = 1e-6
WICK_GAP = 1e-9
DATR_BUFFER = 0.10
# Day 1 is the zone's last candle. Entry starts on day 6.
ENTRY_ON_SESSION = 6


@dataclass(frozen=True)
class Plan:
    entry: float
    stop: float
    target: float


def required_plan(bars: Sequence[Bar], zone: Zone, probability: float) -> Plan | None:
    """The only plan for this zone. None means there is no entry.

    A rejected or uncertain zone has no plan. The 6th-session wait is
    applied by `accepts`, so the prices themselves stay knowable at the close.
    """
    if probability < ACCEPT_AT:
        return None

    leg_in = bars[zone.start]
    uoc = bars[zone.start + 1]
    leg_out = bars[zone.start + 2]
    last = bars[zone.end]

    if _blocked(zone.pattern, leg_in):
        return None

    datr = uoc.datr_14
    if datr is None or datr != datr or datr <= 0:
        return None
    buffer = DATR_BUFFER * datr

    entry = _entry(uoc, leg_out, buffer)
    if entry is None:
        return None

    return Plan(
        entry=entry,
        stop=_stop(zone.pattern, leg_in, uoc, buffer),
        target=last.close,
    )


def entry_is_due(bars: Sequence[Bar], zone: Zone, on_date: str) -> bool:
    """True on the 6th session from the zone's last candle, and on later sessions.

    Sessions after `on_date` are not counted.
    """
    signal = bars[zone.end].date
    if on_date < signal:
        return False
    count = 0
    previous = None
    for bar in bars:
        if bar.date < signal:
            continue
        if bar.date > on_date:
            break
        if bar.date != previous:
            count += 1
            previous = bar.date
        if count >= ENTRY_ON_SESSION:
            return True
    return False


def accepts(
    bars: Sequence[Bar],
    zone: Zone,
    entry: float,
    stop: float,
    target: float,
    on_date: str,
    probability: float,
) -> bool:
    """True when the zone is accepted, the session is the 6th or later, and the prices match."""
    plan = required_plan(bars, zone, probability)
    if plan is None or not entry_is_due(bars, zone, on_date):
        return False
    return _same_price(plan.entry, entry) and _same_price(plan.stop, stop) and _same_price(plan.target, target)


def _blocked(pattern: str, leg_in: Bar) -> bool:
    """DBR closes on its low, or RBR closes on its high."""
    if pattern == "DBR":
        return _same_price(leg_in.low, leg_in.close)
    if pattern == "RBR":
        return _same_price(leg_in.high, leg_in.close)
    return True


def _entry(uoc: Bar, leg_out: Bar, buffer: float) -> float | None:
    """The leg-out is green. A tail under its open uses the UOC, unless the UOC wick reaches that body."""
    if not (leg_out.close > leg_out.open):
        return None

    tail_under_the_open = leg_out.low < leg_out.open - WICK_GAP
    if tail_under_the_open and _upper_wick_reaches_body(uoc, leg_out):
        return leg_out.low
    if _same_price(leg_out.open, leg_out.low):
        return leg_out.open
    if tail_under_the_open:
        anchor = uoc.open if uoc.close < uoc.open else uoc.close
        return anchor + buffer
    return None


def _stop(pattern: str, leg_in: Bar, uoc: Bar, buffer: float) -> float:
    """RBR starts at the UOC low. DBR may start at the leg-in wick when that wick is lower."""
    reference = uoc.low
    leg_in_has_lower_wick = leg_in.low < min(leg_in.open, leg_in.close) - WICK_GAP
    if pattern == "DBR" and leg_in_has_lower_wick and leg_in.low < uoc.low:
        reference = leg_in.low
    return reference - buffer


def _upper_wick_reaches_body(uoc: Bar, leg_out: Bar) -> bool:
    """The UOC upper wick and the leg-out body touch."""
    body_top = max(uoc.open, uoc.close)
    if not (uoc.high > body_top + WICK_GAP):
        return False
    wick_low = body_top
    wick_high = uoc.high
    body_low = min(leg_out.open, leg_out.close)
    body_high = max(leg_out.open, leg_out.close)
    return max(wick_low, body_low) <= min(wick_high, body_high) + WICK_GAP


def _same_price(left: float, right: float) -> bool:
    return abs(left - right) <= PRICE_GAP
