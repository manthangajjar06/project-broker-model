"""Step 5. Higher timeframes exist only for the stock in use.

A chart builds one series. A model run builds three. Closing the stock drops
them. A decision at 11:15 sees the day, week, and month only through the
09:15 candle.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.higher import HigherBook  # noqa: E402
from Model.load import csv_path, load_bars  # noqa: E402


DATA = Path(__file__).resolve().parents[2] / "data"
CLOCK = datetime(2015, 2, 3, 11, 15)


def _names() -> list[str]:
    return sorted(path.name for path in DATA.iterdir())


class Lifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))

    def test_a_chart_builds_only_its_timeframe(self):
        book = HigherBook()
        book.open_chart("RELIANCE", "daily", self.bars)
        self.assertEqual(book.built(), frozenset({"daily"}))
        self.assertGreater(len(book.series("daily", CLOCK)), 0)
        with self.assertRaises(LookupError):
            book.series("weekly", CLOCK)
        with self.assertRaises(LookupError):
            book.series("monthly", CLOCK)

        book.open_chart("RELIANCE", "weekly", self.bars)
        self.assertEqual(book.built(), frozenset({"weekly"}))
        book.open_chart("RELIANCE", "monthly", self.bars)
        self.assertEqual(book.built(), frozenset({"monthly"}))

    def test_a_model_run_builds_all_three_and_close_drops_them(self):
        before = _names()
        book = HigherBook()
        book.run_model("RELIANCE", self.bars)
        self.assertEqual(book.built(), frozenset({"daily", "weekly", "monthly"}))
        for timeframe in ("daily", "weekly", "monthly"):
            self.assertGreater(len(book.series(timeframe, CLOCK)), 0)
        book.close_stock()
        self.assertEqual(book.built(), frozenset())
        self.assertIsNone(book.symbol)
        with self.assertRaises(LookupError):
            book.series("daily", CLOCK)
        self.assertEqual(_names(), before)
        self.assertFalse(any("daily" in name or "weekly" in name or "monthly" in name for name in _names()))

    def test_the_chart_and_the_model_drop_on_their_own(self):
        book = HigherBook()
        book.open_chart("RELIANCE", "daily", self.bars)
        book.run_model("RELIANCE", self.bars)
        book.close_chart()
        self.assertEqual(book.built(), frozenset({"daily", "weekly", "monthly"}))
        book.leave_model()
        self.assertEqual(book.built(), frozenset())

        book.open_chart("RELIANCE", "weekly", self.bars)
        book.run_model("RELIANCE", self.bars)
        book.leave_model()
        self.assertEqual(book.built(), frozenset({"weekly"}))
        book.close_chart()
        self.assertEqual(book.built(), frozenset())


class RelianceClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.book = HigherBook()
        cls.book.run_model("RELIANCE", cls.bars)

    def test_eleven_fifteen_sees_only_the_closed_candle(self):
        daily = self.book.series("daily", CLOCK)
        weekly = self.book.series("weekly", CLOCK)
        monthly = self.book.series("monthly", CLOCK)
        day = daily[-1]
        candle = next(bar for bar in self.bars if bar.date == "2015-02-03" and bar.time == "09:15:00")
        monday = [bar for bar in self.bars if bar.date == "2015-02-02"]

        self.assertTrue(day.partial)
        self.assertEqual(day.last_date, "2015-02-03")
        self.assertEqual(day.last_time, "09:15:00")
        self.assertEqual(day.source_count, 1)
        self.assertEqual(day.open, candle.open)
        self.assertEqual(day.high, candle.high)
        self.assertEqual(day.low, candle.low)
        self.assertEqual(day.close, candle.close)
        self.assertEqual(day.volume, candle.volume)

        previous = next(bar for bar in daily if bar.period == "2015-02-02")
        self.assertFalse(previous.partial)
        self.assertEqual(previous.last_time, "15:15:00")
        self.assertEqual(previous.source_count, 4)
        self.assertEqual(previous.high, max(bar.high for bar in monday))
        self.assertEqual(previous.low, min(bar.low for bar in monday))
        self.assertEqual(previous.close, monday[-1].close)

        for series in (weekly, monthly):
            current = series[-1]
            self.assertTrue(current.partial)
            self.assertEqual(current.last_date, "2015-02-03")
            self.assertEqual(current.last_time, "09:15:00")
            self.assertEqual(current.close, candle.close)
            self.assertEqual(current.source_count, 5)
            included = monday + [candle]
            self.assertEqual(current.high, max(bar.high for bar in included))
            self.assertEqual(current.low, min(bar.low for bar in included))

    def test_a_later_decision_keeps_the_same_completed_bars(self):
        early_clock = datetime(2016, 3, 1, 11, 15)
        late_clock = datetime(2018, 6, 1, 11, 15)
        first = self.book.series("daily", early_clock)
        self.book.series("weekly", late_clock)
        self.book.series("monthly", late_clock)
        second = self.book.series("daily", early_clock)
        self.assertEqual(first, second)
        late = self.book.series("daily", late_clock)
        early_completed = [bar for bar in first if not bar.partial]
        late_prefix = [bar for bar in late if not bar.partial and bar.period < "2016-03-01"]
        self.assertEqual(early_completed, late_prefix)
        weekly_first = self.book.series("weekly", early_clock)
        weekly_again = self.book.series("weekly", early_clock)
        self.assertEqual(weekly_first, weekly_again)

    def test_a_partial_ema_is_not_written_into_the_completed_bar(self):
        day = "2015-04-15"
        partial_clock = datetime(2015, 4, 15, 11, 15)
        close_clock = datetime(2015, 4, 15, 15, 30)
        view = self.book.series("daily", partial_clock)
        partial = view[-1]
        previous = view[-2]
        self.assertEqual(partial.period, day)
        self.assertTrue(partial.partial)
        self.assertIsNotNone(previous.ema_20)
        weight = 2 / 21
        self.assertAlmostEqual(partial.ema_20, partial.close * weight + previous.ema_20 * (1 - weight))

        completed = self.book.series("daily", close_clock)
        finished = next(bar for bar in completed if bar.period == day)
        self.assertFalse(finished.partial)
        right = finished.close * weight + previous.ema_20 * (1 - weight)
        wrong = finished.close * weight + partial.ema_20 * (1 - weight)
        self.assertAlmostEqual(finished.ema_20, right)
        self.assertNotAlmostEqual(finished.ema_20, wrong, delta=1e-6)

        again = self.book.series("daily", partial_clock)
        self.assertEqual(view, again)

    def test_monthly_ema_50_waits_for_fifty_completed_months(self):
        early = self.book.series("monthly", datetime(2017, 1, 3, 11, 15))
        self.assertTrue(all(bar.ema_50 is None for bar in early))
        later = self.book.series("monthly", datetime(2019, 6, 3, 11, 15))
        completed = [bar for bar in later if not bar.partial]
        self.assertGreaterEqual(len(completed), 50)
        self.assertTrue(all(bar.ema_50 is None for bar in completed[:49]))
        self.assertIsNotNone(completed[49].ema_50)


class ShortFiles(unittest.TestCase):
    def test_hyundai_and_vaml_wait_for_warmup_and_about_a_year(self):
        book = HigherBook()
        book.run_model("HYUNDAI")
        self.assertFalse(book.allows_decision(datetime(2024, 11, 8, 11, 15)))
        self.assertFalse(book.allows_decision(datetime(2025, 10, 21, 15, 30)))
        self.assertTrue(book.allows_decision(datetime(2025, 10, 22, 11, 15)))
        book.close_stock()
        self.assertEqual(book.built(), frozenset())

        book.run_model("VAML")
        self.assertFalse(book.allows_decision(datetime(2026, 7, 2, 13, 15)))
        self.assertFalse(book.allows_decision(datetime(2026, 11, 13, 15, 30)))
        book.close_stock()

        reliance = HigherBook()
        reliance.run_model("RELIANCE")
        self.assertFalse(reliance.allows_decision(datetime(2015, 2, 19, 11, 15)))
        self.assertFalse(reliance.allows_decision(datetime(2016, 2, 1, 15, 30)))
        self.assertTrue(reliance.allows_decision(datetime(2016, 2, 2, 11, 15)))


if __name__ == "__main__":
    unittest.main()
