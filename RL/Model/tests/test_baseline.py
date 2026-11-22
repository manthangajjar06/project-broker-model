"""Step 11. The locked 2R plan, the cost, and the paper book.

The capital and the charge in these tests are fixtures. They are not the
training config. The policy is not called.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.baseline import (  # noqa: E402
    BookConfig,
    ChargeSchedule,
    ValidationTrade,
    independent_r,
    locked_plan,
    measure_path,
    report_text,
    run_book,
    share_count,
)
from Model.fill import ClosedCandle  # noqa: E402
from Model.training_config import delivery_rupees  # noqa: E402
from Model.behavior import COMPLETE_STOP  # noqa: E402
from Model.fill import ClosedCandle  # noqa: E402


CAPITAL = 100_000.0
FLAT = 20.0
ATR = 10.0
ENTRY = 100.0
STOP = 90.0
TARGET = 120.0


def _config(capital: float = CAPITAL, flat: float = FLAT, rate: float = 0.0) -> BookConfig:
    return BookConfig(capital, ChargeSchedule(flat, rate))


def _candle(index: int, open_: float, high: float, low: float, close: float) -> ClosedCandle:
    return ClosedCandle(index, open_, high, low, close)


def _trade(**overrides) -> ValidationTrade:
    values = dict(
        symbol="AAA",
        clock=datetime(2022, 1, 3, 11, 15),
        exit_clock=datetime(2022, 1, 3, 13, 15),
        year=2022,
        probability=0.60,
        entry_py=True,
        placed=True,
        outcome="win",
        behavior="uoc_touch",
        plan_entry=ENTRY,
        plan_stop=STOP,
        atr=ATR,
        raw_entry=ENTRY,
        raw_exit=TARGET,
    )
    values.update(overrides)
    return ValidationTrade(**values)


class LockedPlan(unittest.TestCase):
    def test_the_stop_is_the_uoc_low_and_the_target_is_2r(self):
        plan = locked_plan(ENTRY, STOP)
        self.assertEqual(plan.stop, STOP)
        self.assertEqual(plan.target, TARGET)
        self.assertTrue(plan.armed)
        self.assertEqual(locked_plan(ENTRY, STOP), locked_plan(ENTRY, STOP))

    def test_a_stop_that_is_not_below_the_entry_is_masked(self):
        blocked = locked_plan(STOP, STOP)
        self.assertFalse(blocked.armed)


class FillsAndCost(unittest.TestCase):
    def test_a_same_bar_stop_and_target_is_a_loss_at_the_plan_entry(self):
        measured = measure_path(ENTRY, STOP, 110.0, 115.0, ATR, [
            _candle(1, open_=110.0, high=130.0, low=80.0, close=100.0),
        ])
        self.assertEqual(measured.outcome, "loss")
        self.assertEqual(measured.raw_entry, ENTRY)
        self.assertEqual(measured.raw_exit, STOP)
        self.assertEqual(measured.behavior, COMPLETE_STOP)
        self.assertAlmostEqual(independent_r(_as_trade(measured, "loss"), _config()), -1.12)

    def test_a_target_is_a_win_after_slippage_and_the_flat_charge(self):
        measured = measure_path(ENTRY, STOP, 110.0, 110.0, ATR, [
            _candle(1, open_=105.0, high=106.0, low=100.0, close=104.0),
            _candle(2, open_=104.0, high=121.0, low=95.0, close=120.0),
        ])
        self.assertEqual(measured.outcome, "win")
        self.assertEqual(measured.raw_entry, ENTRY)
        self.assertEqual(measured.raw_exit, TARGET)
        self.assertAlmostEqual(independent_r(_as_trade(measured, "win"), _config()), 1.88)

    def test_a_marketable_order_fills_at_the_next_open(self):
        measured = measure_path(ENTRY, STOP, 110.0, 95.0, ATR, [
            _candle(1, open_=102.0, high=121.0, low=101.0, close=120.0),
        ])
        self.assertEqual(measured.outcome, "win")
        self.assertEqual(measured.raw_entry, 102.0)
        self.assertAlmostEqual(independent_r(_as_trade(measured, "win"), _config()), 1.68)

    def test_a_limit_that_never_fills_expires_and_scores_no_r(self):
        candles = [_candle(index, 110.0, 111.0, 101.0, 110.0) for index in range(1, 41)]
        measured = measure_path(ENTRY, STOP, 110.0, 115.0, ATR, candles)
        self.assertEqual(measured.outcome, "no_fill")
        self.assertIsNone(independent_r(_as_trade(measured, "no_fill"), _config()))

    def test_a_short_path_stays_unresolved(self):
        measured = measure_path(ENTRY, STOP, 110.0, 115.0, ATR, [
            _candle(1, open_=110.0, high=111.0, low=105.0, close=110.0),
        ])
        self.assertEqual(measured.outcome, "unresolved")

    def test_bar_40_flattens_an_open_trade_at_the_close(self):
        candles = [_candle(1, 105.0, 106.0, 100.0, 104.0)]
        candles.extend(_candle(index, 104.0, 105.0, 95.0, 104.0) for index in range(2, 41))
        measured = measure_path(ENTRY, STOP, 110.0, 110.0, ATR, candles)
        self.assertEqual(measured.outcome, "time_stop")
        self.assertEqual(measured.raw_exit, 104.0)
        self.assertAlmostEqual(independent_r(_as_trade(measured, "time_stop"), _config()), 0.28)

    def test_one_share_that_risks_more_than_one_percent_is_masked(self):
        self.assertEqual(share_count(500.0, 500.0, ENTRY, STOP, ATR), 0)

    def test_a_session_open_below_the_stop_uses_the_open_without_more_slippage(self):
        measured = measure_path(ENTRY, STOP, 110.0, 110.0, ATR, [
            _candle(1, 105.0, 106.0, 100.0, 104.0),
            ClosedCandle(2, 70.0, 72.0, 70.0, 71.0, session_open=True),
        ])
        self.assertEqual(measured.outcome, "loss")
        self.assertEqual(measured.raw_exit, 70.0)
        self.assertTrue(measured.gap_exit)
        self.assertAlmostEqual(independent_r(_as_trade(measured, "loss"), _config()), -3.07)

    def test_the_delivery_charge_matches_the_zerodha_calculator(self):
        self.assertEqual(delivery_rupees(1000.0, 1100.0, 1000), 2328.55)


class ReportAndBook(unittest.TestCase):
    def test_the_report_has_both_years_and_both_cuts(self):
        trades = [
            _trade(),
            _trade(
                symbol="BBB",
                clock=datetime(2023, 6, 1, 11, 15),
                exit_clock=datetime(2023, 6, 1, 13, 15),
                year=2023,
                probability=0.80,
                entry_py=False,
                outcome="loss",
                behavior="complete_stop",
                raw_exit=STOP,
            ),
        ]
        text = report_text(trades, _config(), symbols=2)
        self.assertEqual(text, report_text(trades, _config(), symbols=2))
        self.assertIn("year 2022", text)
        self.assertIn("year 2023", text)
        self.assertEqual(text.count("cut all"), 2)
        self.assertEqual(text.count("cut entry_py"), 2)
        self.assertIn("behavior complete_stop 0", text)
        self.assertIn("behavior complete_stop 1", text)
        self.assertIn("bucket 0.55-0.65", text)
        self.assertIn("bucket 0.75+", text)
        self.assertIn("win_rate 1.000000", text)
        self.assertIn("win_rate 0.000000", text)
        self.assertIn("average_r 1.880000", text)
        self.assertIn("average_r -1.120000", text)

    def test_two_names_at_one_close_and_a_second_loss_buys_fewer_shares(self):
        first = _trade(symbol="AAA", outcome="loss", behavior="complete_stop", raw_exit=STOP)
        same_close = _trade(
            symbol="BBB",
            outcome="win",
            exit_clock=datetime(2022, 2, 1, 11, 15),
        )
        later = _trade(
            symbol="CCC",
            clock=datetime(2022, 3, 1, 11, 15),
            exit_clock=datetime(2022, 3, 1, 15, 30),
            outcome="loss",
            behavior="complete_stop",
            raw_exit=STOP,
        )
        book = run_book([later, same_close, first], _config())
        self.assertEqual(book.busy_skipped, 1)
        self.assertEqual([item.symbol for item in book.fills], ["AAA", "CCC"])
        self.assertEqual(book.fills[0].shares, 100)
        self.assertEqual(book.fills[1].shares, 98)
        self.assertAlmostEqual(book.fills[0].equity, 98_880.0)
        self.assertAlmostEqual(book.fills[1].equity, 97_782.0)
        self.assertAlmostEqual(book.ending_equity, 97_782.0)
        self.assertGreater(book.max_drawdown, 0.0)

    def test_a_plan_the_cash_cannot_hold_does_not_move_the_book(self):
        book = run_book([_trade()], _config(capital=500.0))
        self.assertEqual(book.masked, 1)
        self.assertEqual(book.fills, ())
        self.assertEqual(book.ending_equity, 500.0)


def _as_trade(measured, outcome: str) -> ValidationTrade:
    return _trade(
        outcome=outcome,
        behavior=measured.behavior,
        placed=measured.placed,
        plan_entry=measured.plan.entry,
        plan_stop=measured.plan.stop,
        raw_entry=measured.raw_entry,
        raw_exit=measured.raw_exit,
        gap_exit=measured.gap_exit,
    )


if __name__ == "__main__":
    unittest.main()
