"""Step 9. Four hand-driven paths on the 3 March 2015 Reliance prices.

The policy is not called. The entry, stop, and target do not move.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.fill import (  # noqa: E402
    CANCEL,
    EXPIRY,
    LEAVE,
    NO_FILL,
    OPEN,
    STOP,
    ClosedCandle,
    begin,
    reveal,
)


# The locked plan printed for Reliance on 3 March 2015 at 09:15.
ENTRY = 204.66069
STOP_PRICE = 203.53931
TARGET = 208.0


def _candle(index: int, open_: float, high: float, low: float, close: float) -> ClosedCandle:
    return ClosedCandle(index, open_, high, low, close)


def _unchanged(walk) -> None:
    if walk.entry != ENTRY or walk.stop != STOP_PRICE or walk.target != TARGET:
        raise AssertionError("the entry, stop, and target moved")


class ScriptedReliancePaths(unittest.TestCase):
    def test_a_bar_that_trades_the_stop_and_the_target_is_a_stop(self):
        # Open above the entry, so the limit can fill, then the same bar hits both prices.
        walk = begin(ENTRY, STOP_PRICE, TARGET, reference_close=210.0, signal_index=0)
        walk = reveal(walk, _candle(1, open_=206.0, high=209.0, low=203.0, close=205.0))
        self.assertEqual(walk.result, STOP)
        self.assertEqual(walk.exit_price, STOP_PRICE)
        _unchanged(walk)

    def test_a_marketable_entry_fills_at_the_next_open(self):
        walk = begin(ENTRY, STOP_PRICE, TARGET, reference_close=200.0, signal_index=0)
        opened = reveal(walk, _candle(1, open_=205.5, high=206.0, low=205.0, close=205.8))
        self.assertEqual(opened.fill_price, 205.5)
        self.assertIsNone(opened.result)
        _unchanged(opened)

        blocked = begin(ENTRY, STOP_PRICE, TARGET, reference_close=200.0, signal_index=0)
        blocked = reveal(blocked, _candle(1, open_=203.0, high=206.0, low=202.0, close=205.0))
        self.assertEqual(blocked.result, NO_FILL)
        self.assertEqual(blocked.score, 0.0)
        _unchanged(blocked)

    def test_a_limit_that_never_trades_the_entry_expires_at_bar_40(self):
        walk = begin(ENTRY, STOP_PRICE, TARGET, reference_close=210.0, signal_index=0)
        for index in range(1, 41):
            walk = reveal(walk, _candle(index, open_=210.0, high=211.0, low=206.0, close=210.0))
        self.assertEqual(walk.result, EXPIRY)
        self.assertEqual(walk.score, 0.0)
        _unchanged(walk)

    def test_an_early_exit_fills_at_the_next_open(self):
        walk = begin(ENTRY, STOP_PRICE, TARGET, reference_close=210.0, signal_index=0)
        filled = reveal(
            walk,
            _candle(1, open_=206.0, high=207.0, low=204.0, close=206.2),
            LEAVE,
        )
        self.assertEqual(filled.fill_price, ENTRY)
        closed = reveal(filled, _candle(2, open_=207.25, high=209.0, low=206.0, close=207.5))
        self.assertEqual(closed.exit_price, 207.25)
        self.assertNotEqual(closed.exit_price, 207.0)
        self.assertNotEqual(closed.exit_price, 204.0)
        _unchanged(closed)

    def test_an_open_below_the_entry_still_buys_at_the_entry(self):
        walk = begin(100.0, 90.0, 120.0, reference_close=115.0, signal_index=0)
        walk = reveal(walk, _candle(1, open_=88.0, high=101.0, low=88.0, close=100.0))
        self.assertEqual(walk.phase, OPEN)
        self.assertEqual(walk.fill_price, 100.0)
        self.assertIsNone(walk.result)

    def test_a_session_open_through_the_stop_sells_at_the_open(self):
        walk = begin(100.0, 90.0, 120.0, reference_close=115.0, signal_index=0)
        held = reveal(walk, _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0))
        closed = reveal(held, ClosedCandle(2, 70.0, 72.0, 70.0, 71.0, session_open=True))
        self.assertEqual(closed.result, STOP)
        self.assertEqual(closed.exit_price, 70.0)
        self.assertTrue(closed.gap_exit)

    def test_a_later_candle_through_the_stop_sells_at_the_stop(self):
        walk = begin(100.0, 90.0, 120.0, reference_close=115.0, signal_index=0)
        held = reveal(walk, _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0))
        closed = reveal(held, _candle(2, open_=70.0, high=72.0, low=70.0, close=71.0))
        self.assertEqual(closed.result, STOP)
        self.assertEqual(closed.exit_price, 90.0)
        self.assertFalse(closed.gap_exit)

    def test_a_session_open_through_the_target_sells_at_the_open(self):
        walk = begin(100.0, 90.0, 120.0, reference_close=115.0, signal_index=0)
        held = reveal(walk, _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0))
        closed = reveal(held, ClosedCandle(2, 130.0, 132.0, 129.0, 131.0, session_open=True))
        self.assertEqual(closed.result, "target")
        self.assertEqual(closed.exit_price, 130.0)
        self.assertTrue(closed.gap_exit)

    def test_a_cancel_scores_zero_and_the_prices_stay(self):
        walk = begin(ENTRY, STOP_PRICE, TARGET, reference_close=210.0, signal_index=0)
        walk = reveal(walk, _candle(1, open_=210.0, high=211.0, low=206.0, close=210.0), CANCEL)
        self.assertEqual(walk.result, "cancel")
        self.assertEqual(walk.score, 0.0)
        _unchanged(walk)


if __name__ == "__main__":
    unittest.main()
