"""Step 14. One paper account, walked forward on the calendar.

A step happens only at an event: a zone is offered while the account is
flat, a bar closes on a working order or an open trade, or that order
ends. One position at a time. Names that signal at the same close are
offered in symbol order. An action the mask forbids cannot be taken.

The take is offered on session 6, which is the Step 8 rule. The snapshot
is built at that close. A later bar is not part of it.

When ask_when_both is set, a candle that trades both the stop and the
target stops and asks which printed first. That is the Step 15 hand call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    STOP,
    TARGET,
    WORKING,
    BothTouched,
    ClosedCandle,
    Walk,
    apply_bar,
    apply_choice,
    begin,
    finish,
)
from Model.higher import HigherBook
from Model.load import Bar
from Model.memory import Memory, Record, context_of, resolution_clock
from Model.reward import PaperBook, Reward, score_walk, stated_chance
from Model.score import ScoredZone, accepted_zones, score_zones
from Model.snapshot import PositionState, Snapshot, snapshot_at
from Model.zones import Zone
from entry import ENTRY_ON_SESSION


ACTIONS = (SKIP, TAKE, KEEP, CANCEL, HOLD, LEAVE)

ResolveBoth = Callable[[BothTouched], str]


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
    chance: float | None = None
    start_equity: float = 0.0


@dataclass(frozen=True)
class Moment:
    """What the policy is shown at one event."""

    symbol: str
    clock: datetime
    mask: dict[str, bool]
    snapshot: Snapshot | None
    remembered: tuple[str, ...] = ()
    chance: float | None = None
    offer: Offer | None = None
    plan: object | None = None


@dataclass(frozen=True)
class StepRecord:
    symbol: str
    clock: datetime
    mask: dict[str, bool]
    action: str
    equity_before: float
    equity_after: float
    reward: Reward
    chance: float | None = None
    behavior: str | None = None
    decided_at: datetime | None = None


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
    ask_when_both: bool = False,
    resolve_both: ResolveBoth | None = None,
) -> list[StepRecord]:
    """Walk one account forward. `book.equity` carries from name to name."""
    from Model.calendar_walk import CalendarWalk

    calendar = CalendarWalk(
        names,
        book,
        first_year,
        last_year,
        offers=offers,
        records=records,
        ask_when_both=ask_when_both,
        resolve_both=resolve_both,
    )
    record: list[StepRecord] = []
    moment = calendar.start()
    while moment is not None:
        action = choose(moment)
        result = calendar.act(action)
        if result.record is not None:
            record.append(result.record)
        record.extend(result.side)
        moment = result.moment
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
    start_equity: float,
    ask_when_both: bool = False,
) -> tuple[StepRecord, Held | None]:
    decision = build_decision(bars, offer.zone, offer.probability, offer.on_date)
    mask = entry_mask(decision)
    snapshot = snapshot_at(bars, offer.zone, offer.clock)
    atr = bars[offer.zone.end].atr_14 if bars[offer.zone.end].atr_14 is not None else 0.0
    context = ()
    if snapshot is not None:
        context = context_of(snapshot, decision.prices, bars[offer.zone.end].close, atr)
    chance = _chance_for(memory, context, offer.clock)
    remembered = tuple(record.symbol for record in memory.visible(offer.clock))
    moment = Moment(
        offer.symbol,
        offer.clock,
        mask,
        snapshot,
        remembered,
        chance,
        offer,
        decision.prices,
    )
    action = choose(moment)
    require_legal(action, mask)
    before = book.equity
    if action == SKIP or decision.prices is None:
        reward = book.mark("skip", 0.0, 0.0, None, None, 1.0)
        written = _experience(offer, bars, moment.snapshot, decision.prices, None, None)
        if written is not None:
            memory.add(written)
        return (
            StepRecord(offer.symbol, offer.clock, mask, action, before, book.equity, reward, chance),
            None,
        )

    signal = bars[offer.bar_index]
    opened = begin(
        decision.prices.entry,
        decision.prices.stop,
        decision.prices.target,
        signal.close,
        offer.zone.end,
        ask_when_both=ask_when_both,
        symbol=offer.symbol,
    )
    held = Held(
        offer.symbol,
        bars,
        opened,
        offer.bar_index + 1,
        atr,
        offer,
        context,
        offer.clock,
        chance,
        start_equity,
    )
    reward = Reward("take", before, before, 0.0, 0.0, None, 0)
    return StepRecord(offer.symbol, offer.clock, mask, action, before, before, reward, chance), held


def _step_position(
    held: Held,
    choose: Callable[[Moment], str],
    book: PaperBook,
    memory: Memory | None = None,
    start_equity: float = 0.0,
    ask_when_both: bool = False,
    resolve_both: ResolveBoth | None = None,
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
        date=bar.date,
        time=bar.time,
    )
    clock = known_clock(bar) or bar.open_at()
    walk_state = _apply_bar(held.walk, candle, resolve_both)
    held = _keep_held(held, walk=walk_state, next_index=held.next_index + 1)
    if walk_state.phase not in (WORKING, OPEN):
        return None, _close_position(held, book, clock, memory)
    mask = manage_mask(walk_state.phase)
    snapshot = _manage_snapshot(held, book, start_equity or held.start_equity, clock)
    action = choose(
        Moment(
            held.symbol,
            clock,
            mask,
            snapshot,
            (),
            held.chance,
            held.offer,
            None,
        )
    )
    require_legal(action, mask)
    before = book.equity
    walk_state = apply_choice(walk_state, action)
    held = _keep_held(held, walk=walk_state)
    if walk_state.phase not in (WORKING, OPEN):
        return None, _close_position(held, book, clock, memory)
    reward = Reward(action, before, before, 0.0, 0.0, None, 0)
    return held, StepRecord(held.symbol, clock, mask, action, before, before, reward, held.chance)


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
    behavior = None
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
        if written is not None:
            behavior = written.behavior
            if memory is not None:
                memory.add(written)
    return StepRecord(
        held.symbol,
        clock,
        {},
        outcome,
        before,
        book.equity,
        reward,
        held.chance,
        behavior,
    )


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


def _apply_bar(walk_state: Walk, candle: ClosedCandle, resolve_both: ResolveBoth | None) -> Walk:
    try:
        return apply_bar(walk_state, candle)
    except BothTouched as hit:
        if resolve_both is None:
            raise
        first = resolve_both(hit)
        if first not in (STOP, TARGET):
            raise ValueError(f"both-touched answer must be stop or target, got {first}")
        opened = replace(
            walk_state,
            phase=OPEN,
            fill_price=walk_state.fill_price if walk_state.fill_price is not None else hit.entry,
        )
        exit_price = hit.stop if first == STOP else hit.target
        return finish(opened, first, score=None, exit_price=exit_price)


def _keep_held(held: Held, walk: Walk | None = None, next_index: int | None = None) -> Held:
    """Keep the offer and the decision context when a later bar arrives."""
    return Held(
        held.symbol,
        held.bars,
        held.walk if walk is None else walk,
        held.next_index if next_index is None else next_index,
        held.atr,
        held.offer,
        held.context,
        held.decided_at,
        held.chance,
        held.start_equity,
    )


def _manage_snapshot(
    held: Held,
    book: PaperBook,
    start_equity: float,
    clock: datetime,
) -> Snapshot | None:
    if held.offer is None:
        return None
    walk_state = held.walk
    if walk_state.phase == WORKING:
        state = "working"
    elif walk_state.phase == OPEN:
        state = "in a trade"
    else:
        state = "flat"
    fill = walk_state.fill_price
    mark = held.bars[held.next_index - 1].close if held.next_index > 0 else walk_state.reference_close
    unrealized = None
    if fill is not None and walk_state.entry > walk_state.stop:
        unrealized = (mark - fill) / (walk_state.entry - walk_state.stop)
    bars_since = held.next_index - 1 - walk_state.signal_index
    bars_in = None if walk_state.phase != OPEN else max(bars_since, 0)
    equity = book.equity
    start = start_equity if start_equity > 0 else equity
    position = PositionState(
        state=state,
        unrealized_r=unrealized,
        bars_since_signal=max(bars_since, 0),
        bars_in_trade=bars_in,
        stop_distance=mark - walk_state.stop,
        target_distance=walk_state.target - mark,
        equity_over_start=equity / start if start else None,
        unrealized_rupee_over_equity=None,
        stop_fraction_of_equity=0.01,
    )
    return snapshot_at(held.bars, held.offer.zone, clock, position)


def _chance_for(memory: Memory, context: tuple, at: datetime) -> float | None:
    """Share of similar past plans that reached the target before the stop."""
    neighbors = memory.neighbors(context, at)
    if not neighbors:
        return None
    known = [
        record.trade_result
        for record in neighbors
        if record.trade_result not in (None, "unresolved")
    ]
    if not known:
        return None
    return stated_chance(known)


def _next_clock(held: Held) -> datetime | None:
    if held.next_index >= len(held.bars):
        return None
    bar = held.bars[held.next_index]
    return known_clock(bar) or bar.open_at()
