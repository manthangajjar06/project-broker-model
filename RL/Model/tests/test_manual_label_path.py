"""Early-window labels and day-6 armed fill without 40-bar expiry."""

from __future__ import annotations

import unittest

from Model.fill import ClosedCandle
from Model.manual_label import (
    LABEL_LOSS,
    LABEL_NOTHING,
    LABEL_PREMATURE,
    LABEL_WIN,
    _entry_fills,
    _first_index_on_or_after_session,
    _scan_early_window,
    _walk_armed_limit,
)
from entry import Plan


def _candle(
    index: int,
    day: str,
    low: float,
    high: float,
    close: float | None = None,
    open_: float | None = None,
) -> ClosedCandle:
    mid = (low + high) / 2
    return ClosedCandle(
        index=index,
        open=mid if open_ is None else open_,
        high=high,
        low=low,
        close=mid if close is None else close,
        session_open=True,
        date=day,
        time="09:15:00",
    )


class EntryFillTests(unittest.TestCase):
    def setUp(self):
        self.plan = Plan(entry=100.0, stop=90.0, target=120.0)

    def test_range_trade_fills(self):
        self.assertTrue(_entry_fills(_candle(1, "2020-01-02", low=99.0, high=101.0), self.plan))

    def test_open_below_entry_above_stop_fills(self):
        candle = _candle(1, "2020-01-02", low=92.0, high=98.0, open_=95.0)
        self.assertTrue(_entry_fills(candle, self.plan))

    def test_open_through_stop_does_not_fill(self):
        candle = _candle(1, "2020-01-02", low=80.0, high=85.0, open_=85.0)
        self.assertFalse(_entry_fills(candle, self.plan))


class EarlyWindowTests(unittest.TestCase):
    def setUp(self):
        self.plan = Plan(entry=100.0, stop=90.0, target=120.0)
        self.signal = "2020-01-01"

    def test_stop_before_fill_is_nothing(self):
        candles = [
            _candle(1, "2020-01-02", low=85.0, high=95.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNotNone(scan.hit)
        self.assertEqual(scan.hit.label, LABEL_NOTHING)
        self.assertFalse(scan.filled)

    def test_entry_then_target_in_early_window_is_premature(self):
        candles = [
            _candle(1, "2020-01-02", low=99.0, high=101.0),
            _candle(2, "2020-01-03", low=110.0, high=125.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNotNone(scan.hit)
        self.assertEqual(scan.hit.label, LABEL_PREMATURE)
        self.assertTrue(scan.filled)

    def test_gap_open_below_entry_then_target_is_premature(self):
        candles = [
            _candle(1, "2020-01-02", low=94.0, high=99.0, open_=96.0),
            _candle(2, "2020-01-03", low=110.0, high=125.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNotNone(scan.hit)
        self.assertEqual(scan.hit.label, LABEL_PREMATURE)
        self.assertTrue(scan.hit.touched_entry)
        self.assertTrue(scan.filled)

    def test_open_below_entry_stop_wick_then_target_is_premature(self):
        candles = [
            _candle(1, "2020-01-02", low=85.0, high=105.0, open_=95.0),
            _candle(2, "2020-01-03", low=110.0, high=125.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNotNone(scan.hit)
        self.assertEqual(scan.hit.label, LABEL_PREMATURE)

    def test_fill_then_stop_in_early_window_is_loss_not_nothing(self):
        candles = [
            _candle(1, "2020-01-02", low=99.0, high=101.0),
            _candle(2, "2020-01-03", low=85.0, high=98.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNotNone(scan.hit)
        self.assertEqual(scan.hit.label, LABEL_LOSS)

    def test_early_fill_unresolved_carries_filled_flag(self):
        # Fill in early window, no stop/target yet — armed walk must keep the trade.
        candles = [
            _candle(1, "2020-01-02", low=99.0, high=101.0),
            _candle(2, "2020-01-03", low=100.0, high=105.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNone(scan.hit)
        self.assertTrue(scan.filled)

    def test_early_window_ignores_session_six_and_later(self):
        candles = [
            _candle(1, "2020-01-02", low=110.0, high=111.0),
            _candle(2, "2020-01-03", low=110.0, high=111.0),
            _candle(3, "2020-01-06", low=110.0, high=111.0),
            _candle(4, "2020-01-07", low=110.0, high=111.0),
            _candle(5, "2020-01-08", low=99.0, high=125.0),
        ]
        scan = _scan_early_window(candles, self.plan, self.signal)
        self.assertIsNone(scan.hit)
        self.assertFalse(scan.filled)

    def test_arm_index_is_session_six(self):
        candles = [
            _candle(1, "2020-01-02", low=1, high=2),
            _candle(2, "2020-01-03", low=1, high=2),
            _candle(3, "2020-01-06", low=1, high=2),
            _candle(4, "2020-01-07", low=1, high=2),
            _candle(5, "2020-01-08", low=1, high=2),
        ]
        index = _first_index_on_or_after_session(candles, self.signal, 6)
        self.assertEqual(index, 4)


class ArmedLimitTests(unittest.TestCase):
    def setUp(self):
        self.plan = Plan(entry=100.0, stop=90.0, target=120.0)

    def test_late_fill_then_stop_is_loss_not_no_fill(self):
        candles = [_candle(index, f"2020-03-{day:02d}", low=110.0, high=111.0) for index, day in enumerate(range(1, 29), start=50)]
        candles.append(_candle(200, "2020-04-01", low=85.0, high=101.0, open_=101.0))
        hit = _walk_armed_limit(candles, self.plan)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.label, LABEL_LOSS)

    def test_fill_then_later_target_is_win(self):
        candles = [
            _candle(10, "2020-02-01", low=99.0, high=101.0),
            _candle(11, "2020-02-02", low=100.0, high=105.0),
            _candle(12, "2020-02-03", low=115.0, high=125.0),
        ]
        hit = _walk_armed_limit(candles, self.plan)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.label, LABEL_WIN)

    def test_gap_open_below_entry_then_target_is_win(self):
        candles = [
            _candle(10, "2020-02-01", low=94.0, high=99.0, open_=96.0),
            _candle(11, "2020-02-02", low=115.0, high=125.0),
        ]
        hit = _walk_armed_limit(candles, self.plan)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.label, LABEL_WIN)

    def test_open_above_target_then_fill_then_stop_is_loss(self):
        candles = [
            _candle(10, "2020-02-01", low=110.0, high=130.0, open_=125.0),
            _candle(11, "2020-02-02", low=94.0, high=126.0, open_=125.0),
            _candle(12, "2020-02-03", low=85.0, high=95.0, open_=94.0),
        ]
        hit = _walk_armed_limit(candles, self.plan)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.label, LABEL_LOSS)

    def test_already_filled_then_target_is_win(self):
        # Early fill carried into day 6 — price never revisits entry.
        candles = [
            _candle(10, "2020-02-01", low=105.0, high=110.0, open_=108.0),
            _candle(11, "2020-02-02", low=115.0, high=125.0, open_=116.0),
        ]
        hit = _walk_armed_limit(candles, self.plan, already_filled=True)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.label, LABEL_WIN)

    def test_never_touches_entry_returns_none(self):
        candles = [
            _candle(10, "2020-02-01", low=110.0, high=115.0),
            _candle(11, "2020-02-02", low=112.0, high=118.0),
        ]
        self.assertIsNone(_walk_armed_limit(candles, self.plan))


if __name__ == "__main__":
    unittest.main()
