"""Step 13. Hand paths produce R and the change in the paper book.

A winner gains. A full stop loses about 1% of equity. A skip leaves the
balance unchanged. A second loss buys fewer shares. A stated chance of 85%
is the share of similar plans that reached the target before the stop.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.baseline import ChargeSchedule, sized_shares, trade_pnl  # noqa: E402
from Model.fill import (  # noqa: E402
    CANCEL,
    LEAVE,
    ClosedCandle,
    begin,
    reveal,
)
from Model.memory import Memory, Record  # noqa: E402
from Model.reward import PaperBook, score_walk, stated_chance, stated_chance_from_memory  # noqa: E402


CAPITAL = 100_000.0
ENTRY = 100.0
STOP = 90.0
TARGET = 120.0
ATR = 10.0
CHARGE = ChargeSchedule(0.0, 0.0, delivery=True)

# The locked plan from the Step 9 Reliance hand path.
RELIANCE_ENTRY = 204.66069
RELIANCE_STOP = 203.53931
RELIANCE_TARGET = 208.0
RELIANCE_ATR = 2.0


def _book() -> PaperBook:
    return PaperBook(CAPITAL, CHARGE)


def _candle(index: int, open_: float, high: float, low: float, close: float) -> ClosedCandle:
    return ClosedCandle(index, open_, high, low, close)


class PaperRewards(unittest.TestCase):
    def test_a_full_stop_is_near_a_1_percent_loss(self):
        book = _book()
        scored = book.mark("stop", ENTRY, STOP, ENTRY, STOP, ATR)
        self.assertEqual(scored.shares, 100)
        self.assertLess(scored.pnl, -CAPITAL * 0.01)
        self.assertGreater(scored.pnl, -CAPITAL * 0.02)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)
        self.assertAlmostEqual(scored.equity_after, CAPITAL + scored.pnl)
        self.assertAlmostEqual(book.equity, scored.equity_after)
        self.assertAlmostEqual(scored.r_after_cost, scored.pnl / (10.0 * 100))

    def test_a_winner_gains_about_2_percent(self):
        book = _book()
        scored = book.mark("target", ENTRY, STOP, ENTRY, TARGET, ATR)
        self.assertGreater(scored.pnl, CAPITAL * 0.015)
        self.assertLess(scored.pnl, CAPITAL * 0.021)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)
        self.assertGreater(book.equity, CAPITAL)

    def test_a_skip_leaves_the_balance_unchanged(self):
        book = _book()
        scored = book.mark("skip", ENTRY, STOP, None, None, ATR)
        self.assertEqual(scored.reward, 0.0)
        self.assertEqual(scored.pnl, 0.0)
        self.assertEqual(scored.shares, 0)
        self.assertEqual(book.equity, CAPITAL)

    def test_cancel_and_expiry_also_score_zero(self):
        for outcome in ("cancel", "expiry", "no_fill"):
            book = _book()
            scored = book.mark(outcome, ENTRY, STOP, ENTRY, STOP, ATR)
            self.assertEqual(scored.reward, 0.0, outcome)
            self.assertEqual(book.equity, CAPITAL, outcome)

    def test_one_share_that_cannot_fit_is_not_taken(self):
        too_much_risk = PaperBook(500.0, CHARGE)
        risky = too_much_risk.mark("stop", ENTRY, STOP, ENTRY, STOP, ATR)
        self.assertEqual(risky.shares, 0)
        self.assertEqual(risky.reward, 0.0)
        self.assertEqual(too_much_risk.equity, 500.0)

        too_little_cash = PaperBook(500.0, CHARGE)
        costly = too_little_cash.mark("target", 1000.0, 999.0, 1000.0, 1002.0, ATR)
        self.assertEqual(costly.shares, 0)
        self.assertEqual(costly.reward, 0.0)
        self.assertEqual(too_little_cash.equity, 500.0)

    def test_a_second_loss_buys_fewer_shares(self):
        book = _book()
        first = book.mark("stop", ENTRY, STOP, ENTRY, STOP, ATR)
        second = book.mark("stop", ENTRY, STOP, ENTRY, STOP, ATR)
        self.assertEqual(first.shares, 100)
        self.assertEqual(second.shares, 98)
        self.assertLess(second.shares, first.shares)
        self.assertLess(book.equity, CAPITAL + first.pnl)


class Step9Paths(unittest.TestCase):
    def test_the_same_bar_stop_uses_the_plan_entry(self):
        walk = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=210.0)
        walk = reveal(walk, _candle(1, open_=206.0, high=209.0, low=203.0, close=205.0))
        self.assertEqual(walk.result, "stop")
        scored = score_walk(CAPITAL, CHARGE, "stop", walk, RELIANCE_ATR)
        self.assertGreater(scored.shares, 0)
        self.assertLess(scored.pnl, 0.0)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)
        self.assertIsNotNone(scored.r_after_cost)

    def test_an_expiry_from_the_hand_path_scores_zero(self):
        walk = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=210.0)
        for index in range(1, 41):
            walk = reveal(walk, _candle(index, 210.0, 211.0, 206.0, 210.0))
        self.assertEqual(walk.result, "expiry")
        scored = score_walk(CAPITAL, CHARGE, walk.result, walk, RELIANCE_ATR)
        self.assertEqual(scored.reward, 0.0)
        self.assertEqual(scored.equity_after, CAPITAL)

    def test_a_marketable_entry_uses_the_next_open(self):
        walk = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=200.0)
        opened = reveal(walk, _candle(1, open_=205.5, high=206.0, low=205.0, close=205.8))
        self.assertEqual(opened.fill_price, 205.5)
        closed = reveal(opened, _candle(2, open_=205.0, high=206.0, low=203.0, close=204.0))
        self.assertEqual(closed.result, "stop")
        self.assertEqual(closed.exit_price, RELIANCE_STOP)
        scored = score_walk(CAPITAL, CHARGE, closed.result, closed, RELIANCE_ATR)
        shares = sized_shares(CAPITAL, CAPITAL, RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_ATR, 205.5)
        at_the_open = trade_pnl(205.5, RELIANCE_STOP, RELIANCE_ATR, shares, CHARGE)
        at_the_plan = trade_pnl(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_ATR, shares, CHARGE)
        self.assertAlmostEqual(scored.pnl, at_the_open)
        self.assertNotAlmostEqual(scored.pnl, at_the_plan)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)

        blocked = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=200.0)
        blocked = reveal(blocked, _candle(1, open_=203.0, high=206.0, low=202.0, close=205.0))
        self.assertEqual(blocked.result, "no_fill")
        missed = score_walk(CAPITAL, CHARGE, blocked.result, blocked, RELIANCE_ATR)
        self.assertEqual(missed.reward, 0.0)
        self.assertEqual(missed.equity_after, CAPITAL)

    def test_an_early_exit_uses_the_next_open(self):
        walk = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=210.0)
        filled = reveal(walk, _candle(1, open_=206.0, high=207.0, low=204.0, close=206.2), LEAVE)
        closed = reveal(filled, _candle(2, open_=207.25, high=209.0, low=206.0, close=207.5))
        self.assertEqual(closed.result, "exit")
        self.assertEqual(closed.exit_price, 207.25)
        scored = score_walk(CAPITAL, CHARGE, closed.result, closed, RELIANCE_ATR)
        shares = scored.shares
        at_the_open = trade_pnl(RELIANCE_ENTRY, 207.25, RELIANCE_ATR, shares, CHARGE)
        at_the_high = trade_pnl(RELIANCE_ENTRY, 207.0, RELIANCE_ATR, shares, CHARGE)
        at_the_low = trade_pnl(RELIANCE_ENTRY, 204.0, RELIANCE_ATR, shares, CHARGE)
        self.assertAlmostEqual(scored.pnl, at_the_open)
        self.assertNotAlmostEqual(scored.pnl, at_the_high)
        self.assertNotAlmostEqual(scored.pnl, at_the_low)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)

    def test_a_session_open_through_the_stop_sells_at_the_open(self):
        walk = begin(ENTRY, STOP, TARGET, reference_close=110.0)
        held = reveal(walk, _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0))
        closed = reveal(held, ClosedCandle(2, 70.0, 72.0, 70.0, 71.0, session_open=True))
        self.assertEqual(closed.result, "stop")
        self.assertEqual(closed.exit_price, 70.0)
        self.assertTrue(closed.gap_exit)
        scored = score_walk(CAPITAL, CHARGE, closed.result, closed, ATR)
        at_the_open = trade_pnl(ENTRY, 70.0, ATR, scored.shares, CHARGE, gap_exit=True)
        with_more_slippage = trade_pnl(ENTRY, 70.0, ATR, scored.shares, CHARGE, gap_exit=False)
        self.assertAlmostEqual(scored.pnl, at_the_open)
        self.assertGreater(scored.pnl, with_more_slippage)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)

    def test_a_session_open_through_the_target_sells_at_the_open(self):
        walk = begin(ENTRY, STOP, TARGET, reference_close=110.0)
        held = reveal(walk, _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0))
        closed = reveal(held, ClosedCandle(2, 130.0, 132.0, 129.0, 131.0, session_open=True))
        self.assertEqual(closed.result, "target")
        self.assertEqual(closed.exit_price, 130.0)
        self.assertTrue(closed.gap_exit)
        scored = score_walk(CAPITAL, CHARGE, closed.result, closed, ATR)
        at_the_open = trade_pnl(ENTRY, 130.0, ATR, scored.shares, CHARGE, gap_exit=True)
        with_more_slippage = trade_pnl(ENTRY, 130.0, ATR, scored.shares, CHARGE, gap_exit=False)
        self.assertAlmostEqual(scored.pnl, at_the_open)
        self.assertGreater(scored.pnl, with_more_slippage)
        self.assertAlmostEqual(scored.reward, scored.pnl / CAPITAL)

    def test_a_cancel_from_the_hand_path_scores_zero(self):
        walk = begin(RELIANCE_ENTRY, RELIANCE_STOP, RELIANCE_TARGET, reference_close=210.0)
        walk = reveal(walk, _candle(1, 210.0, 211.0, 206.0, 210.0), CANCEL)
        self.assertEqual(walk.result, "cancel")
        scored = score_walk(CAPITAL, CHARGE, walk.result, walk, RELIANCE_ATR)
        self.assertEqual(scored.reward, 0.0)
        self.assertEqual(scored.equity_after, CAPITAL)


class StatedChance(unittest.TestCase):
    def test_eighty_five_percent_is_the_share_that_reached_the_target(self):
        outcomes = ["target"] * 17 + ["stop"] * 3
        self.assertAlmostEqual(stated_chance(outcomes), 0.85)

    def test_the_chance_is_read_from_resolved_memory(self):
        records = []
        for index in range(17):
            records.append(_plan(f"T{index}", datetime(2017, 6, 1), "target"))
        for index in range(3):
            records.append(_plan(f"S{index}", datetime(2017, 6, 1), "stop"))
        for index in range(5):
            records.append(_plan(f"L{index}", datetime(2019, 6, 1), "target"))
        records.append(_plan("OPEN", datetime(2017, 6, 1), None))
        memory = Memory(records)
        at = datetime(2018, 1, 1)
        self.assertAlmostEqual(stated_chance_from_memory(memory, at), 0.85)

    def test_unresolved_plans_are_left_out_of_the_chance(self):
        outcomes = ["target"] * 17 + ["stop"] * 3 + ["unresolved"] * 10
        self.assertAlmostEqual(stated_chance(outcomes), 0.85)
        with self.assertRaises(ValueError):
            stated_chance(["unresolved"] * 5)

    def test_an_empty_hand_has_no_chance(self):
        with self.assertRaises(ValueError):
            stated_chance(())


def _plan(symbol: str, resolved: datetime, result: str | None) -> Record:
    return Record(
        symbol=symbol,
        decided_at=resolved,
        resolved_at=resolved,
        context=(1.0,),
        behavior="complete_stop",
        trade_result=result,
        realized_r=None,
    )


if __name__ == "__main__":
    unittest.main()
