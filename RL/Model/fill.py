"""Step 9. Reveal one closed candle at a time and apply the fill rules.

The entry, stop, and target are locked by the take. A later candle cannot
move them. The model is not called. Keep, cancel, hold, and leave are
chosen by hand. Cancel and expiry score 0. The chance from past plans is
absent until Step 12.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


BARS_UNTIL_FLAT = 40

WORKING = "working"
PENDING_MARKET = "pending_market"
OPEN = "open"
DONE = "done"

KEEP = "keep"
CANCEL = "cancel"
HOLD = "hold"
LEAVE = "leave"

STOP = "stop"
TARGET = "target"
EXIT = "exit"
CANCELLED = "cancel"
EXPIRY = "expiry"
NO_FILL = "no_fill"
TIME_STOP = "time_stop"


class BothTouched(RuntimeError):
    """One 2-hour candle traded the stop and the target. The order is not guessed."""

    def __init__(self, symbol: str, date: str, time: str, entry: float, stop: float, target: float):
        self.symbol = symbol
        self.date = date
        self.time = time
        self.entry = entry
        self.stop = stop
        self.target = target
        super().__init__(
            f"{symbol} {date} {time}: this candle traded the stop {stop} and the target {target} "
            f"after entry {entry}. Which one printed first?"
        )


@dataclass(frozen=True)
class ClosedCandle:
    index: int
    open: float
    high: float
    low: float
    close: float
    session_open: bool = False
    date: str = ""
    time: str = ""


@dataclass(frozen=True)
class Walk:
    entry: float
    stop: float
    target: float
    reference_close: float
    signal_index: int
    phase: str
    result: str | None = None
    score: float | None = None
    fill_price: float | None = None
    exit_price: float | None = None
    leave_on_next_open: bool = False
    chance: float | None = None
    gap_exit: bool = False
    ask_when_both: bool = False
    symbol: str = ""


def begin(
    entry: float,
    stop: float,
    target: float,
    reference_close: float,
    signal_index: int = 0,
    ask_when_both: bool = False,
    symbol: str = "",
) -> Walk:
    """Place the locked plan at the close where the take is allowed.

    That close decides whether the order is marketable. The chance is absent.
    """
    phase = PENDING_MARKET if order_is_marketable(entry, reference_close) else WORKING
    return Walk(
        entry=entry,
        stop=stop,
        target=target,
        reference_close=reference_close,
        signal_index=signal_index,
        phase=phase,
        ask_when_both=ask_when_both,
        symbol=symbol,
    )


def apply_bar(walk: Walk, candle: ClosedCandle) -> Walk:
    """Apply this one closed candle. The keep, cancel, hold, or leave choice comes after."""
    if walk.phase == DONE:
        return walk

    if walk.phase == PENDING_MARKET:
        walk = fill_marketable_on_open(walk, candle)
    elif walk.leave_on_next_open:
        return exit_at_this_open(walk, candle)

    was_open = walk.phase == OPEN
    if was_open:
        gapped = session_open_gap(walk, candle)
        if gapped is not None:
            return gapped

    if walk.phase == WORKING:
        walk = fill_working_limit(walk, candle)

    if was_open and walk.phase == OPEN:
        walk = apply_stop_and_target(walk, candle)

    if walk.phase == WORKING and candle_is_the_fortieth(walk, candle):
        return expire_working_limit(walk)

    if walk.phase == OPEN and candle_is_the_fortieth(walk, candle):
        return flatten_at_this_close(walk, candle)

    return walk


def apply_choice(walk: Walk, action: str) -> Walk:
    """Keep or cancel a working limit. Hold or leave an open trade."""
    if walk.phase == DONE:
        return walk
    if walk.phase == WORKING:
        return keep_or_cancel(walk, action)
    if walk.phase == OPEN:
        return hold_or_leave(walk, action)
    return walk


def reveal(walk: Walk, candle: ClosedCandle, action: str | None = None) -> Walk:
    """Apply this one closed candle. Candles after it are not passed in."""
    walk = apply_bar(walk, candle)
    if walk.phase == WORKING:
        return apply_choice(walk, KEEP if action is None else action)
    if walk.phase == OPEN:
        return apply_choice(walk, HOLD if action is None else action)
    return walk


def order_is_marketable(entry: float, reference_close: float) -> bool:
    """An entry already at or above the take-bar close can fill at the next open."""
    return entry >= reference_close


def bar_trades_entry(walk: Walk, candle: ClosedCandle) -> bool:
    """The bar's range traded the entry. The fill is still the entry, not a lower open."""
    return candle.low <= walk.entry <= candle.high


def bar_trades_stop(walk: Walk, candle: ClosedCandle) -> bool:
    return candle.low <= walk.stop


def bar_trades_target(walk: Walk, candle: ClosedCandle) -> bool:
    return candle.high >= walk.target


def fill_marketable_on_open(walk: Walk, candle: ClosedCandle) -> Walk:
    """Fill at the next open when that open is still above the stop."""
    if candle.open <= walk.stop:
        return finish(walk, NO_FILL, score=0.0)
    return replace(walk, phase=OPEN, fill_price=candle.open)


def fill_working_limit(walk: Walk, candle: ClosedCandle) -> Walk:
    """Fill at the entry. A dip from above the entry can stop on that same bar.

    An open below the entry is not the fill. If that bar later trades the
    entry, the buy is the entry. The low before that buy is not a stop.
    """
    if not bar_trades_entry(walk, candle):
        return walk
    if candle.open < walk.entry:
        opened = replace(walk, phase=OPEN, fill_price=walk.entry)
        if bar_trades_stop(opened, candle) and bar_trades_target(opened, candle):
            return apply_stop_and_target(opened, candle)
        if bar_trades_target(opened, candle):
            return finish(opened, TARGET, score=None, exit_price=walk.target)
        return opened
    if bar_trades_stop(walk, candle) and bar_trades_target(walk, candle):
        opened = replace(walk, phase=OPEN, fill_price=walk.entry)
        return apply_stop_and_target(opened, candle)
    if bar_trades_stop(walk, candle):
        return finish(walk, STOP, score=None, fill_price=walk.stop, exit_price=walk.stop)
    opened = replace(walk, phase=OPEN, fill_price=walk.entry)
    if bar_trades_target(opened, candle):
        return finish(opened, TARGET, score=None, exit_price=walk.target)
    return opened


def session_open_gap(walk: Walk, candle: ClosedCandle) -> Walk | None:
    """The first candle of the day. An open through the stop or the target sells there.

    Later candles the same day keep the stop price and the target price.
    """
    if not candle.session_open:
        return None
    if candle.open < walk.stop:
        return finish(walk, STOP, score=None, exit_price=candle.open, gap_exit=True)
    if candle.open > walk.target:
        return finish(walk, TARGET, score=None, exit_price=candle.open, gap_exit=True)
    return None


def apply_stop_and_target(walk: Walk, candle: ClosedCandle) -> Walk:
    """An open bar that reaches both prices is a loss, unless this walk must ask.

    The stop is taken first only when the caller did not ask to be told.
    A baseline walk sets that flag and stops with the stock, the date, and the time.
    """
    if bar_trades_stop(walk, candle) and bar_trades_target(walk, candle):
        if walk.ask_when_both:
            raise BothTouched(walk.symbol, candle.date, candle.time, walk.entry, walk.stop, walk.target)
        return finish(walk, STOP, score=None, exit_price=walk.stop)
    if bar_trades_stop(walk, candle):
        return finish(walk, STOP, score=None, exit_price=walk.stop)
    if bar_trades_target(walk, candle):
        return finish(walk, TARGET, score=None, exit_price=walk.target)
    return walk


def keep_or_cancel(walk: Walk, action: str | None) -> Walk:
    """A working limit that did not fill can be kept or cancelled. Cancel scores 0."""
    choice = KEEP if action is None else action
    if choice == CANCEL:
        return finish(walk, CANCELLED, score=0.0)
    if choice != KEEP:
        raise ValueError(f"a working limit cannot {choice}")
    return walk


def hold_or_leave(walk: Walk, action: str | None) -> Walk:
    """A trade still open at the close can be held or left. Leaving waits for the next open."""
    choice = HOLD if action is None else action
    if choice == LEAVE:
        return replace(walk, leave_on_next_open=True)
    if choice != HOLD:
        raise ValueError(f"an open trade cannot {choice}")
    return walk


def exit_at_this_open(walk: Walk, candle: ClosedCandle) -> Walk:
    """An early exit fills at this candle's open, not at the previous high or low."""
    return finish(walk, EXIT, score=None, exit_price=candle.open)


def expire_working_limit(walk: Walk) -> Walk:
    """Forty bars after the signal, a limit that never filled scores 0."""
    return finish(walk, EXPIRY, score=0.0)


def flatten_at_this_close(walk: Walk, candle: ClosedCandle) -> Walk:
    """Forty bars after the signal, an open trade is closed at this bar's close."""
    return finish(walk, TIME_STOP, score=None, exit_price=candle.close)


def candle_is_the_fortieth(walk: Walk, candle: ClosedCandle) -> bool:
    return candle.index >= walk.signal_index + BARS_UNTIL_FLAT


def finish(
    walk: Walk,
    result: str,
    score: float | None,
    fill_price: float | None = None,
    exit_price: float | None = None,
    gap_exit: bool = False,
) -> Walk:
    """Record the outcome. The entry, stop, and target fields are not replaced."""
    return replace(
        walk,
        phase=DONE,
        result=result,
        score=score,
        fill_price=walk.fill_price if fill_price is None else fill_price,
        exit_price=walk.exit_price if exit_price is None else exit_price,
        leave_on_next_open=False,
        gap_exit=gap_exit,
    )
