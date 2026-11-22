"""Step 5. Daily, weekly, and monthly bars for the stock in use.

The series are built from that stock's 2-hour bars. They are not built for
the rest of the Nifty 100, and they are not written to disk. Opening one
chart builds that timeframe only. A model run builds all three. Closing the
stock drops whatever was built.

A partial bar can update the live EMA and the live ATR for the current
input. That update is not stored on the completed series. The next completed
bar starts from the last completed bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

from Model.clock import ClockError, decision_clock
from Model.load import Bar, csv_path, load_bars


TIMEFRAMES = ("daily", "weekly", "monthly")
WARMUP_BARS = 50
# The plan's "about a year of bars", fixed so the gate does not move.
YEAR = timedelta(days=365)


@dataclass(frozen=True)
class PeriodBar:
    timeframe: str
    period: str
    partial: bool
    open: float
    high: float
    low: float
    close: float
    volume: float
    true_range: float
    ema_20: float | None
    ema_50: float | None
    atr: float | None
    average_volume: float | None
    last_date: str
    last_time: str
    source_count: int


class HigherBook:
    """The higher-timeframe series currently held for one stock."""

    def __init__(self) -> None:
        self._symbol: str | None = None
        self._bars: list[Bar] = []
        self._chart: str | None = None
        self._model = False

    @property
    def symbol(self) -> str | None:
        return self._symbol

    def built(self) -> frozenset[str]:
        if self._symbol is None:
            return frozenset()
        names: set[str] = set()
        if self._model:
            names.update(TIMEFRAMES)
        if self._chart is not None:
            names.add(self._chart)
        return frozenset(names)

    def open_chart(self, symbol: str, timeframe: str, bars: Sequence[Bar] | None = None) -> None:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"{timeframe} is not a daily, weekly, or monthly chart")
        self._activate(symbol, bars)
        self._chart = timeframe

    def run_model(self, symbol: str, bars: Sequence[Bar] | None = None) -> None:
        self._activate(symbol, bars)
        self._model = True

    def close_chart(self) -> None:
        self._chart = None
        if not self._model:
            self.close_stock()

    def leave_model(self) -> None:
        self._model = False
        if self._chart is None:
            self.close_stock()

    def close_stock(self) -> None:
        self._symbol = None
        self._bars = []
        self._chart = None
        self._model = False

    def series(self, timeframe: str, clock: datetime) -> list[PeriodBar]:
        if timeframe not in self.built():
            raise LookupError(f"{timeframe} is not built")
        return build_series(self._bars, timeframe, clock)

    def allows_decision(self, clock: datetime) -> bool:
        """A short file waits for an EMA-50 warmup and about a year of bars."""
        if not self._model or not self._bars:
            return False
        first = date.fromisoformat(self._bars[0].date)
        if clock.date() < first + YEAR:
            return False
        knowable = 0
        for bar in self._bars:
            try:
                closed = decision_clock(bar)
            except ClockError:
                continue
            if closed > clock:
                break
            knowable += 1
        return knowable >= WARMUP_BARS

    def _activate(self, symbol: str, bars: Sequence[Bar] | None) -> None:
        if self._symbol != symbol:
            self.close_stock()
            self._symbol = symbol
            self._bars = list(bars) if bars is not None else load_bars(csv_path(symbol))


def build_series(bars: Sequence[Bar], timeframe: str, clock: datetime) -> list[PeriodBar]:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"{timeframe} is not a daily, weekly, or monthly chart")
    grouped: dict[str, list[Bar]] = {}
    for bar in _knowable(bars, clock):
        grouped.setdefault(_period_key(timeframe, bar.date), []).append(bar)
    ordered = []
    for key in sorted(grouped):
        ordered.append((key, _aggregate(grouped[key]), _is_complete(timeframe, key, clock)))
    completed = [(key, agg) for key, agg, done in ordered if done]
    partials = [(key, agg) for key, agg, done in ordered if not done]
    partial = partials[-1] if partials else None

    completed_aggs = [agg for _, agg in completed]
    completed_ranges = _true_ranges(completed_aggs)
    completed_ema_20 = _ema([agg["close"] for agg in completed_aggs], 20)
    completed_ema_50 = _ema([agg["close"] for agg in completed_aggs], 50)
    completed_atr = _atr(completed_ranges)
    completed_average = _prior_average([agg["volume"] for agg in completed_aggs])

    built = [
        _period_bar(timeframe, key, False, agg, completed_ranges[index], completed_ema_20[index], completed_ema_50[index], completed_atr[index], completed_average[index])
        for index, (key, agg) in enumerate(completed)
    ]
    if partial is not None:
        key, agg = partial
        previous_close = completed_aggs[-1]["close"] if completed_aggs else None
        true_range = _true_range(agg, previous_close)
        built.append(_period_bar(
            timeframe,
            key,
            True,
            agg,
            true_range,
            _live_ema(completed_ema_20, agg["close"], 20),
            _live_ema(completed_ema_50, agg["close"], 50),
            _live_atr(completed_atr, true_range),
            _partial_average(completed_aggs),
        ))
    return built


def _knowable(bars: Sequence[Bar], clock: datetime) -> list[Bar]:
    chosen = []
    for bar in bars:
        try:
            closed = decision_clock(bar)
        except ClockError:
            continue
        if closed > clock:
            break
        chosen.append(bar)
    return chosen


def _period_key(timeframe: str, day: str) -> str:
    if timeframe == "daily":
        return day
    if timeframe == "monthly":
        return day[:7]
    monday = date.fromisoformat(day)
    monday = monday - timedelta(days=monday.weekday())
    return monday.isoformat()


def _is_complete(timeframe: str, key: str, clock: datetime) -> bool:
    day = clock.date()
    if timeframe == "daily":
        period = date.fromisoformat(key)
        if period < day:
            return True
        return (clock.hour, clock.minute, clock.second) >= (15, 30, 0)
    if timeframe == "weekly":
        monday = day - timedelta(days=day.weekday())
        return date.fromisoformat(key) < monday
    return key < f"{day.year:04d}-{day.month:02d}"


def _aggregate(bars: Sequence[Bar]) -> dict:
    return {
        "open": bars[0].open,
        "high": max(bar.high for bar in bars),
        "low": min(bar.low for bar in bars),
        "close": bars[-1].close,
        "volume": sum(bar.volume for bar in bars),
        "last_date": bars[-1].date,
        "last_time": bars[-1].time,
        "source_count": len(bars),
    }


def _true_range(agg: dict, previous_close: float | None) -> float:
    span = agg["high"] - agg["low"]
    if previous_close is None:
        return span
    return max(span, abs(agg["high"] - previous_close), abs(agg["low"] - previous_close))


def _true_ranges(aggs: Sequence[dict]) -> list[float]:
    ranges = []
    previous = None
    for agg in aggs:
        ranges.append(_true_range(agg, previous))
        previous = agg["close"]
    return ranges


def _ema(closes: Sequence[float], length: int) -> list[float | None]:
    values: list[float | None] = [None] * len(closes)
    if len(closes) < length:
        return values
    previous = sum(closes[:length]) / length
    values[length - 1] = previous
    weight = 2 / (length + 1)
    for index in range(length, len(closes)):
        previous = closes[index] * weight + previous * (1 - weight)
        values[index] = previous
    return values


def _atr(true_ranges: Sequence[float]) -> list[float | None]:
    values: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < 14:
        return values
    values[13] = sum(true_ranges[:14]) / 14
    for index in range(14, len(true_ranges)):
        values[index] = (values[index - 1] * 13 + true_ranges[index]) / 14
    return values


def _prior_average(volumes: Sequence[float]) -> list[float | None]:
    averages: list[float | None] = []
    for index in range(len(volumes)):
        if index < 14:
            averages.append(None)
        else:
            averages.append(sum(volumes[index - 14:index]) / 14)
    return averages


def _partial_average(completed: Sequence[dict]) -> float | None:
    if len(completed) < 14:
        return None
    return sum(agg["volume"] for agg in completed[-14:]) / 14


def _live_ema(completed: Sequence[float | None], close: float, length: int) -> float | None:
    if not completed or completed[-1] is None:
        return None
    weight = 2 / (length + 1)
    return close * weight + completed[-1] * (1 - weight)


def _live_atr(completed: Sequence[float | None], true_range: float) -> float | None:
    if not completed or completed[-1] is None:
        return None
    return (completed[-1] * 13 + true_range) / 14


def _period_bar(timeframe, key, partial, agg, true_range, ema_20, ema_50, atr, average) -> PeriodBar:
    return PeriodBar(
        timeframe=timeframe,
        period=key,
        partial=partial,
        open=agg["open"],
        high=agg["high"],
        low=agg["low"],
        close=agg["close"],
        volume=agg["volume"],
        true_range=true_range,
        ema_20=ema_20,
        ema_50=ema_50,
        atr=atr,
        average_volume=average,
        last_date=agg["last_date"],
        last_time=agg["last_time"],
        source_count=agg["source_count"],
    )
