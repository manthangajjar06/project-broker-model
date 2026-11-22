"""Step 14. One paper account, walked forward on the calendar.

A step happens only at an event: a zone is offered while the account is
flat, a bar closes on a working order or an open trade, or that order
ends. One position at a time. Names that signal at the same close are
offered in symbol order. An action the mask forbids cannot be taken.

The take is offered on session 6, which is the Step 8 rule. The snapshot
is built at that close. A later bar is not part of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from Model.clock import known_clock
from Model.decision import SKIP, TAKE, Decision, build_decision
from Model.behavior import PATH_BARS, PathCandle, label_path
from Model.fill import (
    CANCEL,
    HOLD,
    KEEP,
    LEAVE,
    OPEN,
    WORKING,
    ClosedCandle,
    Walk,
    apply_bar,
    apply_choice,
    begin,
)
from Model.higher import HigherBook
from Model.load import Bar
from Model.memory import Memory, Record, context_of, resolution_clock
from Model.reward import PaperBook, Reward, score_walk
from Model.score import ScoredZone, accepted_zones, score_zones
from Model.snapshot import Snapshot, snapshot_at
from Model.zones import Zone
from entry import ENTRY_ON_SESSION


ACTIONS = (SKIP, TAKE, KEEP, CANCEL, HOLD, LEAVE)


@dataclass(frozen=True)
class Name:
    symbol: str
    bars: list[Bar]


@dataclass(frozen=True)
class Offer:
    """One accepted zone, offered at the close of its 6th session."""

    symbol: str
    zone: Zone
    probability: float
    clock: datetime
    on_date: str
    bar_index: int


@dataclass
class Held:
    symbol: str
    bars: list[Bar]
    walk: Walk
    next_index: int
    atr: float
    offer: Offer | None = None
    context: tuple = ()
    decided_at: datetime | None = None


@dataclass(frozen=True)
class Moment:
    """What the policy is shown at one event."""

    symbol: str
    clock: datetime
    mask: dict[str, bool]
    snapshot: Snapshot | None
    remembered: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepRecord:
    symbol: str
    clock: datetime
    mask: dict[str, bool]
    action: str
    equity_before: float
    equity_after: float
    reward: Reward


def entry_mask(decision: Decision) -> dict[str, bool]:
    """The Step 8 mask. Skip is always open. Take is open only when Step 8 allows it."""
    return {
        SKIP: decision.skip_allowed,
        TAKE: decision.take_allowed,
        KEEP: False,
        CANCEL: False,
        HOLD: False,
        LEAVE: False,
    }


def manage_mask(phase: str) -> dict[str, bool]:
    """Keep or cancel while the limit works. Hold or leave while the trade is open."""
    return {
        SKIP: False,
        TAKE: False,
        KEEP: phase == WORKING,
        CANCEL: phase == WORKING,
        HOLD: phase == OPEN,
        LEAVE: phase == OPEN,
    }


def require_legal(action: str, mask: dict[str, bool]) -> None:
    """An action the mask forbids cannot be taken."""
    if action not in mask or not mask[action]:
        raise ValueError(f"{action} is masked")


def collect_offers(names: Sequence[Name], first_year: int, last_year: int) -> list[Offer]:
    """Accepted zones whose 6th session falls inside the year window, symbol order on a tie."""
    offers: list[Offer] = []
    for name in names:
        higher = HigherBook()
        higher.run_model(name.symbol, name.bars)
        try:
            for scored in accepted_zones(score_zones(name.bars)):
                offer = _offer_for(name, scored, higher, first_year, last_year)
                if offer is not None:
                    offers.append(offer)
        finally:
            higher.close_stock()
    offers.sort(key=lambda offer: (offer.clock, offer.symbol))
    return offers


def walk(
    names: Sequence[Name],
    choose: Callable[[Moment], str],
    book: PaperBook,
    first_year: int,
    last_year: int,
    offers: Sequence[Offer] | None = None,
    records: Sequence[Record] = (),
) -> list[StepRecord]:
    """Walk one account forward. `book.equity` carries from name to name."""
    pending = sorted(
        list(offers) if offers is not None else collect_offers(names, first_year, last_year),
        key=lambda offer: (offer.clock, offer.symbol),
    )
    memory = Memory(records)
    by_symbol = {name.symbol: name.bars for name in names}
    held: Held | None = None
    cursor = 0
    record: list[StepRecord] = []

    while cursor < len(pending) or held is not None:
        zone_clock = pending[cursor].clock if cursor < len(pending) else None
        bar_clock = _next_clock(held) if held is not None else None
        if held is not None and (zone_clock is None or bar_clock is None or bar_clock <= zone_clock):
            held, step = _step_position(held, choose, book, memory)
            if step is not None:
                record.append(step)
            continue
        if cursor >= len(pending):
            break
        offer = pending[cursor]
        cursor += 1
        if held is not None:
            before = book.equity
            reward = Reward("busy", before, before, 0.0, 0.0, None, 0)
            record.append(StepRecord(offer.symbol, offer.clock, {}, "busy", before, before, reward))
            continue
        step, held = _step_entry(offer, by_symbol[offer.symbol], choose, book, memory)
        record.append(step)
    return record


def _offer_for(
    name: Name,
    scored: ScoredZone,
    higher: HigherBook,
    first_year: int,
    last_year: int,
) -> Offer | None:
    found = _sixth_session(name.bars, scored.zone)
    if found is None:
        return None
    on_date, bar_index, clock = found
    if clock.year < first_year or clock.year > last_year:
        return None
    if not higher.allows_decision(clock):
        return None
    if bar_index > scored.zone.end + 40:
        return None
    return Offer(name.symbol, scored.zone, scored.probability, clock, on_date, bar_index)


def _sixth_session(bars: Sequence[Bar], zone: Zone) -> tuple[str, int, datetime] | None:
    """The first regular bar of session 6, and the close at which it is knowable."""
    signal = bars[zone.end].date
    count = 0
    previous = None
    day = None
    for bar in bars:
        if bar.date < signal:
            continue
        if bar.date != previous:
            count += 1
            previous = bar.date
        if count == ENTRY_ON_SESSION:
            day = bar.date
            break
    if day is None:
        return None
    for index, bar in enumerate(bars):
        if bar.date < day:
            continue
        if bar.date > day:
            break
        clock = known_clock(bar)
        if clock is not None:
            return day, index, clock
    return None


def _step_entry(
    offer: Offer,
    bars: list[Bar],
    choose: Callable[[Moment], str],
    book: PaperBook,
    memory: Memory,
) -> tuple[StepRecord, Held | None]:
    decision = build_decision(bars, offer.zone, offer.probability, offer.on_date)
    mask = entry_mask(decision)
    remembered = tuple(record.symbol for record in memory.visible(offer.clock))
    moment = Moment(
        offer.symbol,
        offer.clock,
        mask,
        snapshot_at(bars, offer.zone, offer.clock),
        remembered,
    )
    action = choose(moment)
    require_legal(action, mask)
    before = book.equity
    if action == SKIP or decision.prices is None:
        reward = book.mark("skip", 0.0, 0.0, None, None, 1.0)
        written = _experience(offer, bars, moment.snapshot, decision.prices, None, None)
        if written is not None:
            memory.add(written)
        return StepRecord(offer.symbol, offer.clock, mask, action, before, book.equity, reward), None

    signal = bars[offer.bar_index]
    zone_bar = bars[offer.zone.end]
    atr = zone_bar.atr_14 if zone_bar.atr_14 is not None else 0.0
    opened = begin(
        decision.prices.entry,
        decision.prices.stop,
        decision.prices.target,
        signal.close,
        offer.zone.end,
    )
    context = ()
    if moment.snapshot is not None:
        context = context_of(moment.snapshot, decision.prices, bars[offer.zone.end].close, atr)
    held = Held(offer.symbol, bars, opened, offer.bar_index + 1, atr, offer, context, offer.clock)
    reward = Reward("take", before, before, 0.0, 0.0, None, 0)
    return StepRecord(offer.symbol, offer.clock, mask, action, before, before, reward), held


def _step_position(
    held: Held,
    choose: Callable[[Moment], str],
    book: PaperBook,
    memory: Memory | None = None,
) -> tuple[Held | None, StepRecord | None]:
    if held.next_index >= len(held.bars):
        raise RuntimeError(f"{held.symbol} ended while a position was still open")
    bar = held.bars[held.next_index]
    candle = ClosedCandle(
        held.next_index,
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        session_open=bar.time == "09:15:00",
    )
    clock = known_clock(bar) or bar.open_at()
    walk = apply_bar(held.walk, candle)
    held = Held(held.symbol, held.bars, walk, held.next_index + 1, held.atr)
    if walk.phase not in (WORKING, OPEN):
        return None, _close_position(held, book, clock, memory)
    mask = manage_mask(walk.phase)
    action = choose(Moment(held.symbol, clock, mask, None))
    require_legal(action, mask)
    before = book.equity
    walk = apply_choice(walk, action)
    held = Held(held.symbol, held.bars, walk, held.next_index, held.atr)
    if walk.phase not in (WORKING, OPEN):
        return None, _close_position(held, book, clock, memory)
    reward = Reward(action, before, before, 0.0, 0.0, None, 0)
    return held, StepRecord(held.symbol, clock, mask, action, before, before, reward)


def _close_position(
    held: Held,
    book: PaperBook,
    clock: datetime,
    memory: Memory | None = None,
) -> StepRecord:
    outcome = held.walk.result or "expiry"
    before = book.equity
    reward = score_walk(before, book.charge, outcome, held.walk, held.atr)
    book.equity = reward.equity_after
    if held.offer is not None:
        written = _experience(
            held.offer,
            held.bars,
            None,
            None,
            outcome,
            reward.r_after_cost,
            held.context,
        )
        if written is not None and memory is not None:
            memory.add(written)
    return StepRecord(held.symbol, clock, {}, outcome, before, book.equity, reward)


def _experience(
    offer: Offer,
    bars: list[Bar],
    snapshot: Snapshot | None,
    plan,
    trade_result: str | None,
    realized_r: float | None,
    context: tuple = (),
) -> Record | None:
    """One resolved zone. It stays hidden until the 40-bar path has closed."""
    resolved = resolution_clock(bars, offer.zone.end)
    signal = bars[offer.zone.end]
    atr = signal.atr_14
    if resolved is None or atr is None or atr <= 0:
        return None
    window = bars[offer.zone.end + 1 : offer.zone.end + 1 + PATH_BARS]
    candles = [PathCandle(bar.high, bar.low, bar.close) for bar in window]
    behavior = label_path(candles, offer.zone.uoc_low, offer.zone.uoc_high, signal.close, atr).label
    stored = context
    if snapshot is not None:
        stored = context_of(snapshot, plan, signal.close, atr)
    return Record(
        offer.symbol,
        offer.clock,
        resolved,
        stored,
        behavior,
        trade_result,
        realized_r,
    )


def _next_clock(held: Held) -> datetime | None:
    if held.next_index >= len(held.bars):
        return None
    bar = held.bars[held.next_index]
    return known_clock(bar) or bar.open_at()
