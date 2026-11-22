"""Step 10. One path behavior for the candles after a zone.

The policy is not called. A skip receives the same label as a take.
The reference stop is the UOC low. The first matching behavior wins.
"""

from __future__ import annotations

from dataclasses import dataclass


COMPLETE_STOP = "complete_stop"
SLIGHT_BREACH = "slight_breach"
UOC_TOUCH = "uoc_touch"
BASE_NEVER_TOUCHED = "base_never_touched"
UNRESOLVED = "unresolved"

PATH_BARS = 40
SLIGHT_BREACH_ATR = 0.25

# Fill results that mean the order never became a trade.
NO_FILL_RESULTS = {"no_fill", "expiry", "cancel"}


@dataclass(frozen=True)
class PathCandle:
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class TakenTrade:
    """The result of a plan that was taken. The stop is the one the plan placed."""

    result: str
    entry: float
    placed_stop: float
    exit_price: float | None = None


@dataclass(frozen=True)
class Behavior:
    label: str
    breach_atr: float | None
    trade_result: str | None
    realized_r: float | None


def label_path(
    candles: list[PathCandle],
    uoc_low: float,
    uoc_high: float,
    decision_close: float,
    atr: float,
    trade: TakenTrade | None = None,
) -> Behavior:
    """Label the path. `trade` is omitted for a skip."""
    if atr is None or atr <= 0:
        raise ValueError("atr_14 from the signal candle is required")
    path = list(candles)[:PATH_BARS]
    reference = uoc_low

    if is_complete_stop(path, reference, atr):
        label = COMPLETE_STOP
        breach = breach_distance_atr(path, reference, atr)
    elif is_slight_breach(path, reference, uoc_high, atr):
        label = SLIGHT_BREACH
        breach = None
    elif is_uoc_touch(path, uoc_low, uoc_high, reference):
        label = UOC_TOUCH
        breach = None
    elif is_base_never_touched(path, uoc_high, decision_close):
        label = BASE_NEVER_TOUCHED
        breach = None
    else:
        label = UNRESOLVED
        breach = None

    result, realized_r = trade_record(trade)
    return Behavior(label, breach, result, realized_r)


def is_complete_stop(candles: list[PathCandle], reference: float, atr: float) -> bool:
    """A close below the UOC low, or a low more than 0.25 ATR past it.

    A later rally does not remove this label.
    """
    limit = reference - SLIGHT_BREACH_ATR * atr
    for candle in candles:
        if candle.close < reference:
            return True
        if candle.low < limit:
            return True
    return False


def is_slight_breach(candles: list[PathCandle], reference: float, uoc_high: float, atr: float) -> bool:
    """A low nicks the stop by at most 0.25 ATR, then price closes back above the UOC high."""
    limit = reference - SLIGHT_BREACH_ATR * atr
    breach_at = None
    for index, candle in enumerate(candles):
        went_past = candle.low < reference
        within_band = candle.low >= limit
        if went_past and within_band:
            breach_at = index
            break
    if breach_at is None:
        return False
    later = candles[breach_at + 1:]
    closed_above_stop = any(candle.close > reference for candle in later)
    closed_above_uoc_high = any(candle.close > uoc_high for candle in later)
    return closed_above_stop and closed_above_uoc_high


def is_uoc_touch(candles: list[PathCandle], uoc_low: float, uoc_high: float, reference: float) -> bool:
    """Price trades into the UOC without passing the stop, then closes above the UOC high."""
    for index, candle in enumerate(candles):
        if trades_uoc_without_passing_stop(candle, uoc_low, uoc_high, reference):
            later = candles[index + 1:]
            if any(later_candle.close > uoc_high for later_candle in later):
                return True
    return False


def is_base_never_touched(candles: list[PathCandle], uoc_high: float, decision_close: float) -> bool:
    """Price dips below the decision close, never reaches the UOC, then closes back above it."""
    if any(candle.low <= uoc_high for candle in candles):
        return False
    dip_at = None
    for index, candle in enumerate(candles):
        if candle.low < decision_close:
            dip_at = index
            break
    if dip_at is None:
        return False
    return any(candle.close > decision_close for candle in candles[dip_at + 1:])


def trades_uoc_without_passing_stop(
    candle: PathCandle,
    uoc_low: float,
    uoc_high: float,
    reference: float,
) -> bool:
    overlaps_zone = candle.low <= uoc_high and candle.high >= uoc_low
    stays_above_stop = candle.low >= reference
    return overlaps_zone and stays_above_stop


def breach_distance_atr(candles: list[PathCandle], reference: float, atr: float) -> float:
    """How far past the reference stop the lowest low went, in ATR."""
    if not candles:
        return 0.0
    deepest = min(candle.low for candle in candles)
    if deepest >= reference:
        return 0.0
    return (reference - deepest) / atr


def trade_record(trade: TakenTrade | None) -> tuple[str | None, float | None]:
    """A skip stores no trade result. A take stores the result and R against its own stop."""
    if trade is None:
        return None, None
    result = "no_fill" if trade.result in NO_FILL_RESULTS else trade.result
    if trade.result == "exit":
        result = "early_exit"
    if trade.result == "time_stop":
        result = "time_stop"
    if trade.exit_price is None or trade.entry == trade.placed_stop:
        return result, None
    realized_r = (trade.exit_price - trade.entry) / (trade.entry - trade.placed_stop)
    return result, realized_r
