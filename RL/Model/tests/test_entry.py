"""Step 7. Reliance plans match the entry, stop, and target rules.

A candle after the zone does not change the plan. The chart draws the same prices.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.load import csv_path, load_bars  # noqa: E402
from Model.score import score_zones  # noqa: E402
from entry import accepts, entry_is_due, required_plan  # noqa: E402


WICK_GAP = 1e-9


def _tail(bar) -> bool:
    return bar.low < bar.open - WICK_GAP


def _touches(uoc, leg_out) -> bool:
    body_top = max(uoc.open, uoc.close)
    if not (uoc.high > body_top + WICK_GAP):
        return False
    body_low = min(leg_out.open, leg_out.close)
    body_high = max(leg_out.open, leg_out.close)
    return max(body_top, body_low) <= min(uoc.high, body_high) + WICK_GAP


def _expected(bars, zone):
    leg_in = bars[zone.start]
    uoc = bars[zone.start + 1]
    leg_out = bars[zone.start + 2]
    if zone.pattern == "DBR" and abs(leg_in.low - leg_in.close) <= 1e-6:
        return None
    if zone.pattern == "RBR" and abs(leg_in.high - leg_in.close) <= 1e-6:
        return None
    datr = uoc.datr_14
    if datr is None or datr <= 0:
        return None
    buffer = 0.10 * datr
    if _tail(leg_out) and _touches(uoc, leg_out):
        entry = leg_out.low
    elif abs(leg_out.open - leg_out.low) <= 1e-6:
        entry = leg_out.open
    elif _tail(leg_out):
        anchor = uoc.open if uoc.close < uoc.open else uoc.close
        entry = anchor + buffer
    else:
        return None
    reference = uoc.low
    leg_in_wick = leg_in.low < min(leg_in.open, leg_in.close) - WICK_GAP
    if zone.pattern == "DBR" and leg_in_wick and leg_in.low < uoc.low:
        reference = leg_in.low
    return entry, reference - buffer, bars[zone.end].close


class ReliancePlans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.scored = score_zones(cls.bars)
        cls.zones = [item.zone for item in cls.scored]

    def test_a_handful_match_the_rules(self):
        seen = {"skip": 0, "open": 0, "tail": 0, "touch": 0}
        checked = 0
        for item in self.scored:
            zone = item.zone
            leg_in = self.bars[zone.start]
            uoc = self.bars[zone.start + 1]
            leg_out = self.bars[zone.start + 2]
            if uoc.datr_14 is None or uoc.datr_14 <= 0:
                continue
            if item.probability < 0.55:
                self.assertIsNone(required_plan(self.bars, zone, item.probability))
                continue
            kind = _kind(zone.pattern, leg_in, uoc, leg_out)
            if seen.get(kind, 0) >= 2:
                continue
            seen[kind] = seen.get(kind, 0) + 1
            checked += 1
            expected = _expected(self.bars, zone)
            plan = required_plan(self.bars, zone, item.probability)
            due = _nth_session(self.bars, zone, 6)
            if expected is None:
                self.assertIsNone(plan)
                self.assertFalse(accepts(self.bars, zone, leg_out.open, uoc.low, leg_out.close, due, item.probability))
                continue
            self.assertIsNotNone(plan)
            self.assertAlmostEqual(plan.entry, expected[0])
            self.assertAlmostEqual(plan.stop, expected[1])
            self.assertAlmostEqual(plan.target, expected[2])
            self.assertTrue(accepts(self.bars, zone, plan.entry, plan.stop, plan.target, due, item.probability))
            self.assertFalse(accepts(self.bars, zone, plan.entry + 1, plan.stop, plan.target, due, item.probability))
        self.assertGreaterEqual(seen["skip"], 1)
        self.assertGreaterEqual(seen["open"], 1)
        self.assertGreaterEqual(seen["tail"], 1)
        self.assertGreaterEqual(checked, 4)

    def test_a_candle_after_the_zone_changes_nothing(self):
        zone = next(
            item.zone
            for item in self.scored
            if item.zone.end + 1 < len(self.bars) and required_plan(self.bars, item.zone, item.probability) is not None
        )
        probability = next(item.probability for item in self.scored if item.zone is zone)
        before = required_plan(self.bars, zone, probability)
        changed = list(self.bars)
        later = changed[zone.end + 1]
        changed[zone.end + 1] = dataclasses.replace(
            later,
            open=later.open + 25,
            high=later.high + 40,
            low=later.low - 15,
            close=later.close + 30,
        )
        after = required_plan(changed, zone, probability)
        self.assertEqual(before, after)

    def test_entry_waits_until_the_sixth_session_and_rejected_zones_stay_rejected(self):
        taken = next(item for item in self.scored if required_plan(self.bars, item.zone, item.probability) is not None)
        plan = required_plan(self.bars, taken.zone, taken.probability)
        first = _nth_session(self.bars, taken.zone, 1)
        fifth = _nth_session(self.bars, taken.zone, 5)
        sixth = _nth_session(self.bars, taken.zone, 6)
        self.assertFalse(entry_is_due(self.bars, taken.zone, first))
        self.assertFalse(entry_is_due(self.bars, taken.zone, fifth))
        self.assertTrue(entry_is_due(self.bars, taken.zone, sixth))
        self.assertFalse(accepts(self.bars, taken.zone, plan.entry, plan.stop, plan.target, fifth, taken.probability))
        self.assertTrue(accepts(self.bars, taken.zone, plan.entry, plan.stop, plan.target, sixth, taken.probability))

        rejected = next(item for item in self.scored if item.probability <= 0.45)
        self.assertIsNone(required_plan(self.bars, rejected.zone, rejected.probability))
        later = _nth_session(self.bars, rejected.zone, 6)
        self.assertFalse(accepts(self.bars, rejected.zone, 1, 1, 1, later, rejected.probability))

    def test_the_chart_draws_the_same_prices(self):
        script = Path(__file__).resolve().parent / "chart_plans.mjs"
        completed = subprocess.run(
            ["node", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        chart_plans = json.loads(completed.stdout)
        self.assertEqual(len(chart_plans), len(self.zones))
        shown = 0
        last = self.bars[-1].date
        for item, chart_plan in zip(self.scored, chart_plans):
            zone = item.zone
            plan = required_plan(self.bars, zone, item.probability)
            self.assertEqual(chart_plan["start"], zone.start)
            self.assertEqual(chart_plan["end"], zone.end)
            if plan is None or not entry_is_due(self.bars, zone, last):
                self.assertIsNone(chart_plan["entry"])
                continue
            self.assertAlmostEqual(chart_plan["entry"], plan.entry)
            self.assertAlmostEqual(chart_plan["stop"], plan.stop)
            self.assertAlmostEqual(chart_plan["target"], plan.target)
            shown += 1
        self.assertGreater(shown, 0)


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


def _kind(pattern, leg_in, uoc, leg_out) -> str:
    if pattern == "DBR" and abs(leg_in.low - leg_in.close) <= 1e-6:
        return "skip"
    if pattern == "RBR" and abs(leg_in.high - leg_in.close) <= 1e-6:
        return "skip"
    if _tail(leg_out) and _touches(uoc, leg_out):
        return "touch"
    if abs(leg_out.open - leg_out.low) <= 1e-6:
        return "open"
    if _tail(leg_out):
        return "tail"
    return "other"


if __name__ == "__main__":
    unittest.main()
