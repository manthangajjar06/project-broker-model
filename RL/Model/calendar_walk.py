"""Pauseable calendar for Step 14 and Step 15.

`start()` returns the first moment. `act(action)` applies it and returns
the reward, whether the walk is done, the step record, and the next moment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

from Model.clock import known_clock
from Model.decision import SKIP, TAKE, build_decision
from Model.behavior import PATH_BARS, PathCandle, label_path
from Model.environment import (
    Held,
    Moment,
    Name,
    Offer,
    StepRecord,
    _apply_bar,
    _chance_for,
    _keep_held,
    _manage_snapshot,
    collect_offers,
    entry_mask,
    manage_mask,
    require_legal,
)
from Model.fill import (
    OPEN,
    WORKING,
    BothTouched,
    ClosedCandle,
    begin,
)
from Model.memory import Memory, Record, context_of, resolution_clock
from Model.reward import PaperBook, Reward, score_walk
from Model.snapshot import snapshot_at


ResolveBoth = Callable[[BothTouched], str]


@dataclass
class ActResult:
    reward: float
    done: bool
    record: StepRecord | None
    moment: Moment | None
    side: tuple[StepRecord, ...] = ()


class CalendarWalk:
    """One paper account walked forward, pausing at every policy decision."""

    def __init__(
        self,
        names: Sequence[Name],
        book: PaperBook,
        first_year: int,
        last_year: int,
        offers: Sequence[Offer] | None = None,
        records: Sequence[Record] = (),
        ask_when_both: bool = False,
        resolve_both: ResolveBoth | None = None,
    ):
        self.names = list(names)
        self.book = book
        self.first_year = first_year
        self.last_year = last_year
        self.pending = sorted(
            list(offers) if offers is not None else collect_offers(names, first_year, last_year),
            key=lambda offer: (offer.clock, offer.symbol),
        )
        self.memory = Memory(records)
        self.by_symbol = {name.symbol: name.bars for name in names}
        self.ask_when_both = ask_when_both
        self.resolve_both = resolve_both
        self.held: Held | None = None
        self.cursor = 0
        self.start_equity = book.equity
        self.moment: Moment | None = None
        self._awaiting: str | None = None
        self._entry_offer: Offer | None = None
        self._entry_decision = None
        self._entry_mask = None
        self._entry_snapshot = None
        self._entry_context: tuple = ()
        self._entry_chance: float | None = None
        self.clocks: list[datetime] = []
        self.trades: list[StepRecord] = []
        self.behavior_labels: list[tuple[tuple, str]] = []

    def start(self) -> Moment | None:
        """Advance to the first decision, or None when the window is empty."""
        return self._advance_to_decision()

    def act(self, action: str) -> ActResult:
        if self.moment is None or self._awaiting is None:
            return ActResult(0.0, True, None, None)
        require_legal(action, self.moment.mask)
        if self._awaiting == "entry":
            record, self.held = self._finish_entry(action)
            if record.action in (SKIP, TAKE):
                self.clocks.append(record.clock)
            reward = float(record.reward.reward)
            moment = self._advance_to_decision()
            side = tuple(self.trades)
            self.trades.clear()
            reward += sum(float(item.reward.reward) for item in side)
            return ActResult(reward, moment is None, record, moment, side)
        record = self._finish_manage(action)
        reward = 0.0 if record is None else float(record.reward.reward)
        moment = self._advance_to_decision()
        side = tuple(self.trades)
        self.trades.clear()
        # A close that happened on the choice itself is `record`, not side.
        if record is not None and record.action in (
            "stop",
            "target",
            "exit",
            "time_stop",
            "cancel",
            "expiry",
            "no_fill",
        ):
            pass
        reward += sum(float(item.reward.reward) for item in side)
        return ActResult(reward, moment is None, record, moment, side)

    def _advance_to_decision(self) -> Moment | None:
        while True:
            zone_clock = self.pending[self.cursor].clock if self.cursor < len(self.pending) else None
            bar_clock = self._next_clock() if self.held is not None else None
            if self.held is not None and (zone_clock is None or bar_clock is None or bar_clock <= zone_clock):
                moment = self._open_manage()
                if moment is not None:
                    return moment
                continue
            if self.cursor >= len(self.pending):
                self.moment = None
                self._awaiting = None
                return None
            offer = self.pending[self.cursor]
            self.cursor += 1
            if self.held is not None:
                before = self.book.equity
                reward = Reward("busy", before, before, 0.0, 0.0, None, 0)
                self.trades.append(
                    StepRecord(offer.symbol, offer.clock, {}, "busy", before, before, reward)
                )
                continue
            return self._open_entry(offer)

    def _open_entry(self, offer: Offer) -> Moment:
        bars = self.by_symbol[offer.symbol]
        decision = build_decision(bars, offer.zone, offer.probability, offer.on_date)
        mask = entry_mask(decision)
        snapshot = snapshot_at(bars, offer.zone, offer.clock)
        atr = bars[offer.zone.end].atr_14 if bars[offer.zone.end].atr_14 is not None else 0.0
        context = ()
        if snapshot is not None:
            context = context_of(snapshot, decision.prices, bars[offer.zone.end].close, atr)
        chance = _chance_for(self.memory, context, offer.clock)
        remembered = tuple(record.symbol for record in self.memory.visible(offer.clock))
        self._awaiting = "entry"
        self._entry_offer = offer
        self._entry_decision = decision
        self._entry_mask = mask
        self._entry_snapshot = snapshot
        self._entry_context = context
        self._entry_chance = chance
        self.moment = Moment(
            offer.symbol,
            offer.clock,
            mask,
            snapshot,
            remembered,
            chance,
            offer,
            decision.prices,
        )
        return self.moment

    def _finish_entry(self, action: str) -> tuple[StepRecord, Held | None]:
        offer = self._entry_offer
        decision = self._entry_decision
        mask = self._entry_mask
        bars = self.by_symbol[offer.symbol]
        before = self.book.equity
        chance = self._entry_chance
        if action == SKIP or decision.prices is None:
            reward = self.book.mark("skip", 0.0, 0.0, None, None, 1.0)
            written = self._experience(offer, bars, self._entry_snapshot, decision.prices, None, None)
            behavior = None
            if written is not None:
                behavior = written.behavior
                self.memory.add(written)
                self.behavior_labels.append((written.context, written.behavior))
            self._awaiting = None
            return (
                StepRecord(
                    offer.symbol,
                    offer.clock,
                    mask,
                    action,
                    before,
                    self.book.equity,
                    reward,
                    chance,
                    behavior,
                    offer.clock,
                ),
                None,
            )

        signal = bars[offer.bar_index]
        atr = bars[offer.zone.end].atr_14 if bars[offer.zone.end].atr_14 is not None else 0.0
        opened = begin(
            decision.prices.entry,
            decision.prices.stop,
            decision.prices.target,
            signal.close,
            offer.zone.end,
            ask_when_both=self.ask_when_both,
            symbol=offer.symbol,
        )
        held = Held(
            offer.symbol,
            bars,
            opened,
            offer.bar_index + 1,
            atr,
            offer,
            self._entry_context,
            offer.clock,
            chance,
            self.start_equity,
        )
        reward = Reward("take", before, before, 0.0, 0.0, None, 0)
        self._awaiting = None
        return (
            StepRecord(offer.symbol, offer.clock, mask, action, before, before, reward, chance, None, offer.clock),
            held,
        )

    def _open_manage(self) -> Moment | None:
        assert self.held is not None
        held = self.held
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
        walk_state = _apply_bar(held.walk, candle, self.resolve_both)
        held = _keep_held(held, walk=walk_state, next_index=held.next_index + 1)
        self.held = held
        if walk_state.phase not in (WORKING, OPEN):
            record = self._close(held, clock)
            self.held = None
            self.trades.append(record)
            return None
        mask = manage_mask(walk_state.phase)
        snapshot = _manage_snapshot(held, self.book, self.start_equity, clock)
        self._awaiting = "manage"
        self.moment = Moment(
            held.symbol,
            clock,
            mask,
            snapshot,
            (),
            held.chance,
            held.offer,
            None,
        )
        return self.moment

    def _finish_manage(self, action: str) -> StepRecord | None:
        assert self.held is not None
        from Model.fill import apply_choice

        before = self.book.equity
        walk_state = apply_choice(self.held.walk, action)
        held = _keep_held(self.held, walk=walk_state)
        self.held = held
        self._awaiting = None
        if walk_state.phase not in (WORKING, OPEN):
            clock = self.moment.clock if self.moment is not None else datetime.min
            record = self._close(held, clock)
            self.held = None
            return record
        reward = Reward(action, before, before, 0.0, 0.0, None, 0)
        return StepRecord(
            held.symbol,
            self.moment.clock,
            self.moment.mask,
            action,
            before,
            before,
            reward,
            held.chance,
            None,
            held.decided_at,
        )

    def _close(self, held: Held, clock: datetime) -> StepRecord:
        outcome = held.walk.result or "expiry"
        before = self.book.equity
        reward = score_walk(before, self.book.charge, outcome, held.walk, held.atr)
        self.book.equity = reward.equity_after
        behavior = None
        if held.offer is not None:
            written = self._experience(
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
                self.memory.add(written)
                self.behavior_labels.append((written.context, written.behavior))
        return StepRecord(
            held.symbol,
            clock,
            {},
            outcome,
            before,
            self.book.equity,
            reward,
            held.chance,
            behavior,
            held.decided_at,
        )

    def _experience(
        self,
        offer: Offer,
        bars: list,
        snapshot,
        plan,
        trade_result: str | None,
        realized_r: float | None,
        context: tuple = (),
    ) -> Record | None:
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

    def _next_clock(self) -> datetime | None:
        if self.held is None or self.held.next_index >= len(self.held.bars):
            return None
        bar = self.held.bars[self.held.next_index]
        return known_clock(bar) or bar.open_at()
