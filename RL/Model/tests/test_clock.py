"""Step 2. Four Reliance opens map to their closes.

A zone ending on the 09:15 candle cannot see the 13:15 or 15:15 bars of that day.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.clock import (  # noqa: E402
    ClockError,
    bars_knowable_at,
    decision_clock,
    is_daily_close,
    known_clock,
)
from Model.load import csv_path, load_bars  # noqa: E402


def _at(date: str, clock: str) -> datetime:
    return datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S")


class RelianceClock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.by_key = {(bar.date, bar.time): bar for bar in cls.bars}

    def test_four_opens_map_to_the_four_closes(self):
        day = "2015-02-02"
        expected = {
            "09:15:00": "11:15:00",
            "11:15:00": "13:15:00",
            "13:15:00": "15:15:00",
            "15:15:00": "15:30:00",
        }
        for open_time, close_time in expected.items():
            bar = self.by_key[(day, open_time)]
            self.assertEqual(decision_clock(bar), _at(day, close_time))
        self.assertTrue(is_daily_close(self.by_key[(day, "15:15:00")]))
        self.assertFalse(is_daily_close(self.by_key[(day, "09:15:00")]))
        self.assertFalse(is_daily_close(self.by_key[(day, "13:15:00")]))

    def test_zone_ending_on_the_0915_candle_hides_later_bars(self):
        day = "2015-02-03"
        end = self.by_key[(day, "09:15:00")]
        clock = decision_clock(end)
        self.assertEqual(clock, _at(day, "11:15:00"))
        standard = [bar for bar in self.bars if bar.date < "2015-11-11"]
        visible = {(bar.date, bar.time) for bar in bars_knowable_at(standard, clock)}
        self.assertIn((day, "09:15:00"), visible)
        self.assertIn(("2015-02-02", "15:15:00"), visible)
        self.assertNotIn((day, "11:15:00"), visible)
        self.assertNotIn((day, "13:15:00"), visible)
        self.assertNotIn((day, "15:15:00"), visible)
        self.assertNotIn(("2015-02-04", "09:15:00"), visible)

    def test_the_daily_close_reveals_that_session_only(self):
        day = "2015-02-02"
        clock = decision_clock(self.by_key[(day, "15:15:00")])
        self.assertEqual(clock, _at(day, "15:30:00"))
        standard = [bar for bar in self.bars if bar.date < "2015-11-11"]
        visible = {(bar.date, bar.time) for bar in bars_knowable_at(standard, clock)}
        for open_time in ("09:15:00", "11:15:00", "13:15:00", "15:15:00"):
            self.assertIn((day, open_time), visible)
        self.assertNotIn(("2015-02-03", "09:15:00"), visible)

    def test_a_session_outside_the_four_opens_has_no_close(self):
        odd = self.by_key[("2015-11-11", "17:38:00")]
        self.assertIsNone(known_clock(odd))
        with self.assertRaises(ClockError):
            decision_clock(odd)


if __name__ == "__main__":
    unittest.main()
