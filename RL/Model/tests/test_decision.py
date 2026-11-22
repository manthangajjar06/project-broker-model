"""Step 8. The take-or-skip choice on one Reliance zone.

Prices match entry.py. A rejected zone cannot be taken.
Session 5 cannot take. Session 6 can, when the stop is below the entry.
A candle after the zone close does not move the prices.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.decision import (  # noqa: E402
    build_decision,
    prices_at_close,
    skip_is_allowed,
    stop_is_strictly_below_entry,
    take_is_allowed,
)
from Model.load import csv_path, load_bars  # noqa: E402
from Model.score import score_zones  # noqa: E402
from entry import Plan, required_plan  # noqa: E402


class RelianceDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.scored = score_zones(cls.bars)
        cls.taken = next(
            item
            for item in cls.scored
            if required_plan(cls.bars, item.zone, item.probability) is not None
        )
        cls.rejected = next(item for item in cls.scored if item.probability <= 0.45)

    def test_the_choice_is_locked(self):
        zone = self.taken.zone
        probability = self.taken.probability
        expected = required_plan(self.bars, zone, probability)
        self.assertIsNotNone(expected)

        stored = prices_at_close(self.bars, zone, probability)
        self.assertEqual(stored, expected)
        self.assertTrue(stop_is_strictly_below_entry(stored))

        fifth = _nth_session(self.bars, zone, 5)
        sixth = _nth_session(self.bars, zone, 6)
        early = build_decision(self.bars, zone, probability, fifth)
        due = build_decision(self.bars, zone, probability, sixth)
        self.assertFalse(early.take_allowed, "session 5 masks the take")
        self.assertTrue(due.take_allowed, "session 6 allows the take")
        self.assertTrue(early.skip_allowed)
        self.assertTrue(due.skip_allowed)
        self.assertEqual(early.prices, due.prices)

        rejected = build_decision(
            self.bars,
            self.rejected.zone,
            self.rejected.probability,
            _nth_session(self.bars, self.rejected.zone, 6),
        )
        self.assertIsNone(rejected.prices)
        self.assertFalse(rejected.take_allowed, "a rejected zone masks the take")
        self.assertTrue(rejected.skip_allowed)

        blocked = take_is_allowed(Plan(entry=100.0, stop=100.0, target=110.0), True)
        self.assertFalse(blocked, "a stop that is not below the entry masks the take")
        self.assertTrue(skip_is_allowed())

        changed = list(self.bars)
        later = changed[zone.end + 1]
        changed[zone.end + 1] = dataclasses.replace(
            later,
            open=later.open + 25,
            high=later.high + 40,
            low=later.low - 15,
            close=later.close + 30,
        )
        moved = prices_at_close(changed, zone, probability)
        self.assertEqual(moved, stored, "a later candle does not move the prices")


def _nth_session(bars, zone, number: int) -> str:
    signal = bars[zone.end].date
    previous = None
    count = 0
    for bar in bars:
        if bar.date < signal:
            continue
        if bar.date != previous:
            count += 1
            previous = bar.date
        if count == number:
            return bar.date
    raise AssertionError(f"zone ending {signal} does not have session {number}")


if __name__ == "__main__":
    unittest.main()
