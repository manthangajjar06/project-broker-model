"""Step 12. The experience of zones that have already resolved.

A record stores the decision-time snapshot and the plan. It does not store
the memory summary. A later decision can read a record only when that
record's outcome time is already at or before the decision. The 16 closest
visible records are the neighbors. Fewer than 16 leaves the summary empty.

The memory is rebuilt from the records on every pass. The order is the
outcome time, then the decision time, then the symbol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from Model.behavior import (
    BASE_NEVER_TOUCHED,
    COMPLETE_STOP,
    PATH_BARS,
    SLIGHT_BREACH,
    UOC_TOUCH,
)
from Model.clock import known_clock
from Model.load import Bar
from Model.snapshot import FootprintSummary, Snapshot, TimeframeContext
from entry import Plan


NEIGHBOR_COUNT = 16

BEHAVIORS = (
    COMPLETE_STOP,
    SLIGHT_BREACH,
    UOC_TOUCH,
    BASE_NEVER_TOUCHED,
)

ORDER_STATE = {
    "flat": 0.0,
    "working": 1.0,
    "in a trade": 2.0,
}


@dataclass(frozen=True)
class Record:
    """One accepted zone after its path has resolved."""

    symbol: str
    decided_at: datetime
    resolved_at: datetime
    context: tuple[float | None, ...]
    behavior: str
    trade_result: str | None
    realized_r: float | None


@dataclass(frozen=True)
class BehaviorSummary:
    """The share of the 16 neighbors, and the average R of the taken trades."""

    share: float
    average_r: float | None


@dataclass(frozen=True)
class MemorySummary:
    complete_stop: BehaviorSummary
    slight_breach: BehaviorSummary
    uoc_touch: BehaviorSummary
    base_never_touched: BehaviorSummary


class Memory:
    """The records a decision is allowed to remember."""

    def __init__(self, records: Sequence[Record]):
        self.records = order_records(records)

    def add(self, record: Record) -> None:
        """Rebuild in time order with this resolved zone included."""
        self.records = order_records([*self.records, record])

    def visible(self, at: datetime) -> tuple[Record, ...]:
        """Records whose outcome is already known at this clock."""
        return tuple(record for record in self.records if record.resolved_at <= at)

    def neighbors(self, context: Sequence[float | None], at: datetime) -> tuple[Record, ...]:
        """The 16 closest visible records. Empty when fewer than 16 are visible."""
        ready = self.visible(at)
        if len(ready) < NEIGHBOR_COUNT:
            return ()
        ranked = sorted(ready, key=lambda record: _rank(context, record))
        return tuple(ranked[:NEIGHBOR_COUNT])

    def summary(self, context: Sequence[float | None], at: datetime) -> MemorySummary | None:
        """Empty until 16 neighbors exist."""
        found = self.neighbors(context, at)
        if len(found) < NEIGHBOR_COUNT:
            return None
        return summarize(found)


def order_records(records: Sequence[Record]) -> tuple[Record, ...]:
    """The same records, in the order a pass rebuilds them."""
    return tuple(sorted(records, key=_record_order))


def resolution_clock(bars: Sequence[Bar], zone_end: int) -> datetime | None:
    """The close of the last regular bar in the 40-bar path.

    A Muhurat bar has no session close, so it is not the outcome time.
    The record stays hidden until this clock.
    """
    clock = None
    window = bars[zone_end + 1 : zone_end + 1 + PATH_BARS]
    for bar in window:
        known = known_clock(bar)
        if known is not None:
            clock = known
    return clock


def context_of(
    snapshot: Snapshot,
    plan: Plan | None,
    close: float,
    atr: float | None,
) -> tuple[float | None, ...]:
    """The scale-free context. Raw prices stay out. The memory summary is absent."""
    values: list[float | None] = []

    for feature in snapshot.features:
        values.append(_number(feature))

    values.append(_number(snapshot.p_accept))

    values.extend(
        _number(value)
        for value in (
            snapshot.leg_in_body_pct,
            snapshot.leg_in_upper_wick_pct,
            snapshot.leg_in_lower_wick_pct,
            snapshot.uoc_body_pct,
            snapshot.uoc_upper_wick_pct,
            snapshot.uoc_lower_wick_pct,
            snapshot.leg_out_body_pct,
            snapshot.leg_out_upper_wick_pct,
            snapshot.leg_out_lower_wick_pct,
            snapshot.close_ema20_over_atr,
            snapshot.ema_gap_over_atr,
            snapshot.zone_height_over_atr,
            snapshot.datr_over_atr,
        )
    )

    state = ORDER_STATE.get(snapshot.order_state)
    if state is None:
        raise ValueError(f"{snapshot.order_state} is not flat, working, or in a trade")
    values.append(state)

    values.extend(
        _number(value)
        for value in (
            snapshot.unrealized_r,
            _whole(snapshot.bars_since_signal),
            _whole(snapshot.bars_in_trade),
            snapshot.distance_to_stop,
            snapshot.distance_to_target,
            snapshot.equity_over_start,
            snapshot.unrealized_rupee_over_equity,
            snapshot.stop_fraction_of_equity,
        )
    )

    values.extend(_footprint(snapshot.base_footprint))
    values.extend(_footprint(snapshot.leg_out_footprint))
    values.extend(_footprint(snapshot.retest_footprint))
    values.extend(_timeframe(snapshot.daily))
    values.extend(_timeframe(snapshot.weekly))
    values.extend(_timeframe(snapshot.monthly))
    values.extend(_plan(plan, close, atr))
    return tuple(values)


def distance(left: Sequence[float | None], right: Sequence[float | None]) -> float:
    """Euclidean distance over the coordinates both records actually have.

    A missing coordinate is skipped. The result is divided by the number of
    shared coordinates so a longer overlap is not treated as farther away.
    """
    if len(left) != len(right):
        raise ValueError("two contexts must have the same length")
    total = 0.0
    shared = 0
    for first, second in zip(left, right):
        if first is None or second is None:
            continue
        gap = first - second
        total += gap * gap
        shared += 1
    if shared == 0:
        return math.inf
    return math.sqrt(total / shared)


def summarize(neighbors: Sequence[Record]) -> MemorySummary:
    """One share and one average R for each of the four behaviors."""
    count = len(neighbors)
    if count == 0:
        raise ValueError("a summary needs the neighbors")
    return MemorySummary(
        complete_stop=_behavior_summary(neighbors, COMPLETE_STOP, count),
        slight_breach=_behavior_summary(neighbors, SLIGHT_BREACH, count),
        uoc_touch=_behavior_summary(neighbors, UOC_TOUCH, count),
        base_never_touched=_behavior_summary(neighbors, BASE_NEVER_TOUCHED, count),
    )


def _behavior_summary(neighbors: Sequence[Record], label: str, count: int) -> BehaviorSummary:
    group = [record for record in neighbors if record.behavior == label]
    taken = [record.realized_r for record in group if record.realized_r is not None]
    average = None if not taken else sum(taken) / len(taken)
    return BehaviorSummary(len(group) / count, average)


def _plan(plan: Plan | None, close: float, atr: float | None) -> tuple[float | None, ...]:
    """Skip is 0. A taken plan stores its three distances in ATR, not the prices."""
    if plan is None:
        return (0.0, None, None, None)
    if atr is None or atr != atr or atr <= 0:
        return (1.0, None, None, None)
    return (
        1.0,
        (plan.entry - close) / atr,
        (plan.entry - plan.stop) / atr,
        (plan.target - plan.entry) / atr,
    )


def _footprint(summary: FootprintSummary | None) -> tuple[float | None, ...]:
    if summary is None:
        return (None, None, None, None, None)
    return (
        _number(summary.delta_over_volume),
        _number(summary.poc_location),
        _number(summary.lower_third_buy_share),
        _number(summary.upper_third_buy_share),
        _number(summary.imbalance_share),
    )


def _timeframe(context: TimeframeContext) -> tuple[float | None, ...]:
    return (
        _number(context.close_ema20_over_atr),
        _number(context.ema_gap_over_atr),
        _number(context.true_range_over_atr),
        _number(context.volume_over_average),
    )


def _record_order(record: Record) -> tuple:
    return (record.resolved_at, record.decided_at, record.symbol)


def _rank(context: Sequence[float | None], record: Record) -> tuple:
    return (distance(context, record.context), record.resolved_at, record.decided_at, record.symbol)


def _number(value: float | None) -> float | None:
    if value is None or value != value:
        return None
    return float(value)


def _whole(value: int | None) -> float | None:
    if value is None:
        return None
    return float(value)
