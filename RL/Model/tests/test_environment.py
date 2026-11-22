"""Step 14. One paper account walked across two names.

The balance carries from name to name. A snapshot does not read a bar
after its clock. The mask at a decision is the Step 8 mask.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.baseline import ChargeSchedule, trade_pnl  # noqa: E402
from Model.decision import TAKE, build_decision  # noqa: E402
from Model.environment import (  # noqa: E402
    Held,
    Name,
    _step_position,
    collect_offers,
    entry_mask,
    require_legal,
    walk,
)
from Model.fill import begin  # noqa: E402
from Model.load import csv_path, load_bars  # noqa: E402
from Model.memory import Record  # noqa: E402
from Model.reward import PaperBook  # noqa: E402
from Model.snapshot import snapshot_at  # noqa: E402


def _choose(moment):
    if moment.mask[TAKE]:
        return TAKE
    for action, allowed in moment.mask.items():
        if allowed:
            return action
    raise AssertionError(moment.mask)


class TwoNameWalk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = [Name(symbol, load_bars(csv_path(symbol))) for symbol in ("RELIANCE", "TCS")]
        cls.offers = collect_offers(cls.names, 2016, 2016)
        cls.bars = {name.symbol: name.bars for name in cls.names}

    def test_the_balance_carries_and_the_mask_matches_step_8(self):
        self.assertGreaterEqual(len(self.offers), 2)
        clocks = [(offer.clock, offer.symbol) for offer in self.offers]
        self.assertEqual(clocks, sorted(clocks))

        first = next(offer for offer in self.offers if _allowed(self.bars, offer))
        later = next(
            offer
            for offer in self.offers
            if offer.symbol != first.symbol
            and offer.clock > first.clock + timedelta(days=30)
            and _allowed(self.bars, offer)
        )
        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        steps = walk(self.names, _choose, book, 2016, 2016, offers=(first, later))

        self.assertGreaterEqual(len({step.symbol for step in steps}), 2)
        for earlier, nxt in zip(steps, steps[1:]):
            self.assertEqual(nxt.equity_before, earlier.equity_after)
        self.assertTrue(any(step.reward.pnl != 0 for step in steps))
        self.assertNotEqual(book.equity, 100_000.0)

        for offer in (first, later):
            decision = build_decision(self.bars[offer.symbol], offer.zone, offer.probability, offer.on_date)
            logged = next(step for step in steps if step.clock == offer.clock and step.symbol == offer.symbol and step.action == TAKE)
            self.assertEqual(logged.mask, entry_mask(decision))
            self.assertTrue(logged.mask[TAKE])

    def test_a_snapshot_does_not_read_a_later_bar(self):
        offer = self.offers[0]
        bars = self.bars[offer.symbol]
        original = snapshot_at(bars, offer.zone, offer.clock)
        changed = list(bars)
        later = changed[offer.bar_index + 1]
        changed[offer.bar_index + 1] = dataclasses.replace(later, close=later.close + 50, high=later.high + 50)
        again = snapshot_at(changed, offer.zone, offer.clock)
        self.assertEqual(original, again)

    def test_a_masked_action_cannot_be_taken(self):
        with self.assertRaises(ValueError):
            require_legal(TAKE, {TAKE: False})

    def test_a_signal_during_an_open_trade_is_skipped(self):
        first, second = _two_allowed(self.offers, self.bars)
        second = dataclasses.replace(second, clock=first.clock + timedelta(minutes=1))
        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        steps = walk(self.names, _choose, book, 2016, 2016, offers=(second, first))
        self.assertEqual(steps[0].action, TAKE)
        self.assertEqual(steps[0].symbol, first.symbol)
        busy = [step for step in steps if step.action == "busy"]
        self.assertEqual([step.symbol for step in busy], [second.symbol])
        self.assertEqual(busy[0].reward.reward, 0.0)
        self.assertFalse(any(step.symbol == second.symbol and step.action == TAKE for step in steps))

    def test_the_same_close_is_offered_in_symbol_order(self):
        first, second = _two_allowed(self.offers, self.bars)
        clock = first.clock
        reversed_offers = (
            dataclasses.replace(second, clock=clock),
            dataclasses.replace(first, clock=clock),
        )
        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        steps = walk(self.names, _skip, book, 2016, 2016, offers=reversed_offers)
        offered = [step.symbol for step in steps if step.action == "skip"]
        self.assertEqual(offered, sorted(offered))
        self.assertEqual(offered, sorted([first.symbol, second.symbol]))

    def test_cancel_scores_zero_and_leave_exits_at_the_next_open(self):
        offer = _limit_offer(self.offers, self.bars)
        prices = build_decision(self.bars[offer.symbol], offer.zone, offer.probability, offer.on_date).prices
        bars = list(self.bars[offer.symbol])
        span = prices.target - prices.entry
        # Above the entry and below the target, so the working limit is not filled.
        quiet = dataclasses.replace(
            bars[offer.bar_index + 1],
            open=prices.entry + span * 0.55,
            high=prices.entry + span * 0.75,
            low=prices.entry + span * 0.25,
            close=prices.entry + span * 0.55,
        )
        bars[offer.bar_index + 1] = quiet
        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        held = _held(offer, bars, prices, offer.bar_index + 1)
        held, step = _step_position(held, _cancel, book)
        self.assertIsNone(held)
        self.assertEqual(step.action, "cancel")
        self.assertEqual(step.reward.reward, 0.0)
        self.assertEqual(book.equity, 100_000.0)

        opening = prices.entry + span * 0.25
        filled = dataclasses.replace(
            bars[offer.bar_index + 1],
            open=opening,
            high=prices.entry + span * 0.5,
            low=prices.entry,
            close=opening,
        )
        nxt = dataclasses.replace(
            bars[offer.bar_index + 2],
            open=prices.entry + span * 0.2,
            high=prices.entry + span * 0.4,
            low=prices.entry + span * 0.1,
            close=prices.entry + span * 0.2,
        )
        bars[offer.bar_index + 1] = filled
        bars[offer.bar_index + 2] = nxt
        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        held = _held(offer, bars, prices, offer.bar_index + 1)
        held, leaving = _step_position(held, _leave, book)
        self.assertEqual(leaving.action, "leave")
        self.assertEqual(book.equity, 100_000.0)
        held, closed = _step_position(held, _leave, book)
        self.assertIsNone(held)
        self.assertEqual(closed.action, "exit")
        expected = trade_pnl(prices.entry, nxt.open, held_atr(offer, self.bars), closed.reward.shares, book.charge)
        self.assertAlmostEqual(closed.reward.pnl, expected)
        self.assertAlmostEqual(closed.reward.reward, expected / 100_000.0)

    def test_a_resolved_skip_is_remembered_by_the_next_decision(self):
        from Model.memory import resolution_clock

        first = next(item for item in self.offers if _allowed(self.bars, item))
        resolved = resolution_clock(self.bars[first.symbol], first.zone.end)
        self.assertIsNotNone(resolved)
        later = next(
            item
            for item in self.offers
            if item is not first and item.clock >= resolved and _allowed(self.bars, item)
        )
        seen = []

        def choose(moment):
            seen.append(moment)
            return _skip(moment)

        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        walk(self.names, choose, book, 2016, 2016, offers=(first, later))
        self.assertGreaterEqual(len(seen), 2)
        self.assertIn(first.symbol, seen[1].remembered)
        self.assertNotIn(later.symbol, seen[0].remembered)

    def test_a_2016_decision_sees_2015_and_not_2017(self):
        offer = next(item for item in self.offers if _allowed(self.bars, item))
        past = _record("Y2015", datetime(2015, 6, 1), "target")
        future = _record("Y2017", datetime(2017, 6, 1), "stop")
        seen = []

        def choose(moment):
            seen.append(moment)
            return _skip(moment)

        book = PaperBook(100_000.0, ChargeSchedule(0.0, 0.0, delivery=True))
        walk(self.names, choose, book, 2016, 2016, offers=(offer,), records=(future, past))
        self.assertIn("Y2015", seen[0].remembered)
        self.assertNotIn("Y2017", seen[0].remembered)


def _allowed(bars, offer) -> bool:
    decision = build_decision(bars[offer.symbol], offer.zone, offer.probability, offer.on_date)
    return decision.take_allowed


def _limit_offer(offers, bars):
    """A day-6 plan whose entry is still below that bar's close, so the order is a limit."""
    for offer in offers:
        if not _allowed(bars, offer):
            continue
        prices = build_decision(bars[offer.symbol], offer.zone, offer.probability, offer.on_date).prices
        if prices.entry < bars[offer.symbol][offer.bar_index].close and prices.target > prices.entry:
            return offer
    raise AssertionError("no working limit was offered")


def _two_allowed(offers, bars):
    first = next(offer for offer in offers if _allowed(bars, offer))
    second = next(offer for offer in offers if offer.symbol != first.symbol and _allowed(bars, offer))
    return first, second


def _skip(moment):
    if moment.mask.get("skip"):
        return "skip"
    if moment.mask.get("keep"):
        return "keep"
    if moment.mask.get("hold"):
        return "hold"
    raise AssertionError(moment.mask)


def _cancel(moment):
    if moment.mask.get("cancel"):
        return "cancel"
    raise AssertionError(moment.mask)


def _leave(moment):
    if moment.mask.get("leave"):
        return "leave"
    if moment.mask.get("keep"):
        return "keep"
    raise AssertionError(moment.mask)


def _held(offer, bars, prices, index):
    opened = begin(prices.entry, prices.stop, prices.target, bars[offer.bar_index].close, offer.zone.end)
    return Held(offer.symbol, bars, opened, index, held_atr(offer, {offer.symbol: bars}))


def held_atr(offer, bars) -> float:
    atr = bars[offer.symbol][offer.zone.end].atr_14
    return atr if atr is not None else 2.0


def _record(symbol: str, resolved: datetime, result: str) -> Record:
    return Record(symbol, resolved, resolved, (1.0,), "uoc_touch", result, 1.0)


if __name__ == "__main__":
    unittest.main()
