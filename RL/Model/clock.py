"""Step 2. The decision clock.

The timestamp on a row is the candle open. The candle is knowable only at
its close. A zone is decided at the close of its last candle. Bars whose
close is after that clock stay hidden.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from Model.load import Bar


# Open on the row -> close, on the same date. The 15:15 close is the daily close.
CLOSE_BY_OPEN = {
    "09:15:00": "11:15:00",
    "11:15:00": "13:15:00",
    "13:15:00": "15:15:00",
    "15:15:00": "15:30:00",
}

DAILY_CLOSE_OPEN = "15:15:00"


class ClockError(ValueError):
    """This candle open has no close in the decision-clock table."""


def known_clock(bar: Bar) -> datetime | None:
    """The close for a regular session. A Muhurat bar has none."""
    close = CLOSE_BY_OPEN.get(bar.time)
    if close is None:
        return None
    return datetime.strptime(f"{bar.date} {close}", "%Y-%m-%d %H:%M:%S")


def decision_clock(bar: Bar) -> datetime:
    """The close at which this candle, and a zone ending on it, become knowable."""
    clock = known_clock(bar)
    if clock is None:
        raise ClockError(f"{bar.date} {bar.time} is not one of the four session opens")
    return clock


def is_daily_close(bar: Bar) -> bool:
    """True when this candle's close is the daily close."""
    decision_clock(bar)
    return bar.time == DAILY_CLOSE_OPEN


def bars_knowable_at(bars: Sequence[Bar], clock: datetime) -> list[Bar]:
    """Bars whose close is at or before the decision clock, in stored order."""
    return [bar for bar in bars if decision_clock(bar) <= clock]
