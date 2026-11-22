"""Step 6. A Reliance snapshot uses only bars that have already closed.

A bar after the decision clock changes none of the values. The raw footprint
and the raw prices stay out. The memory summary is not part of this step.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.clock import decision_clock  # noqa: E402
from Model.higher import build_series  # noqa: E402
from Model.load import FootprintLevel, csv_path, load_bars  # noqa: E402
from Model.predict import load_frozen_model, predict_probability  # noqa: E402
from Model.score import features_for, true_range_and_atr  # noqa: E402
from Model.snapshot import (  # noqa: E402
    SESSION_MINUTES,
    Snapshot,
    footprint_summary,
    session_fraction,
    snapshot_at,
)
from Model.zones import find_zones  # noqa: E402


def _same(left, right) -> bool:
    if isinstance(left, float) and isinstance(right, float):
        if left != left and right != right:
            return True
        return left == right
    if dataclasses.is_dataclass(left) and dataclasses.is_dataclass(right):
        return all(_same(getattr(left, name), getattr(right, name)) for name in left.__dataclass_fields__)
    if isinstance(left, tuple) and isinstance(right, tuple):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _wick(bar, part: str) -> float:
    span = bar.high - bar.low
    if part == "body":
        value = abs(bar.close - bar.open)
    elif part == "upper":
        value = bar.high - max(bar.open, bar.close)
    else:
        value = min(bar.open, bar.close) - bar.low
    return 0.0 if span <= 0 else (value / span) * 100


class HandFootprint(unittest.TestCase):
    def test_the_four_summaries_are_ratios(self):
        bar = load_bars(csv_path("RELIANCE"))[0]
        bar = dataclasses.replace(
            bar,
            open=10,
            high=12,
            low=10,
            close=11,
            volume=18,
            delta=3,
            footprint=(
                FootprintLevel(10, 1, 1),
                FootprintLevel(11, 9, 1),
                FootprintLevel(12, 0, 6),
            ),
        )
        summary = footprint_summary(bar)
        self.assertAlmostEqual(summary.delta_over_volume, 3 / 18)
        self.assertAlmostEqual(summary.poc_location, (11 - 10) / 2)
        self.assertAlmostEqual(summary.lower_third_buy_share, 0.5)
        self.assertAlmostEqual(summary.upper_third_buy_share, 0.0)
        self.assertAlmostEqual(summary.imbalance_share, 2 / 3)


class RelianceSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.zone = next(
            zone
            for zone in find_zones(cls.bars)
            if cls.bars[zone.end].time == "09:15:00"
            and cls.bars[zone.end].date >= "2017-06-01"
            and cls.bars[zone.end].atr_14
            and cls.bars[zone.end].datr_14
            and cls.bars[zone.end].ema_20
            and cls.bars[zone.end].ema_50
            and cls.bars[zone.start + 1].footprint
            and cls.bars[zone.end].footprint
        )
        cls.clock = decision_clock(cls.bars[cls.zone.end])
        cls.snapshot = snapshot_at(cls.bars, cls.zone, cls.clock)

    def test_every_value_recomputes_from_closed_bars(self):
        zone = self.zone
        signal = self.bars[zone.end]
        base = self.bars[zone.start + 1]
        leg_in = self.bars[zone.start]
        prefix = self.bars[: zone.end + 1]
        true_range, atr = true_range_and_atr(prefix)
        features = tuple(features_for(prefix, zone, true_range, atr))
        self.assertEqual(len(self.snapshot.features), 31)
        self.assertTrue(_same(self.snapshot.features, features))
        self.assertAlmostEqual(self.snapshot.p_accept, predict_probability(load_frozen_model(), list(features)))

        self.assertAlmostEqual(self.snapshot.leg_in_body_pct, _wick(leg_in, "body"))
        self.assertAlmostEqual(self.snapshot.leg_in_upper_wick_pct, _wick(leg_in, "upper"))
        self.assertAlmostEqual(self.snapshot.leg_in_lower_wick_pct, _wick(leg_in, "lower"))
        self.assertAlmostEqual(self.snapshot.uoc_body_pct, _wick(base, "body"))
        self.assertAlmostEqual(self.snapshot.uoc_upper_wick_pct, _wick(base, "upper"))
        self.assertAlmostEqual(self.snapshot.uoc_lower_wick_pct, _wick(base, "lower"))
        self.assertAlmostEqual(self.snapshot.leg_out_body_pct, _wick(signal, "body"))
        self.assertAlmostEqual(self.snapshot.leg_out_upper_wick_pct, _wick(signal, "upper"))
        self.assertAlmostEqual(self.snapshot.leg_out_lower_wick_pct, _wick(signal, "lower"))

        self.assertAlmostEqual(self.snapshot.close_ema20_over_atr, (signal.close - signal.ema_20) / signal.atr_14)
        self.assertAlmostEqual(self.snapshot.ema_gap_over_atr, (signal.ema_20 - signal.ema_50) / signal.atr_14)
        self.assertAlmostEqual(self.snapshot.zone_height_over_atr, (zone.uoc_high - zone.uoc_low) / signal.atr_14)
        self.assertAlmostEqual(self.snapshot.datr_over_atr, signal.datr_14 / signal.atr_14)
        span = base.high - base.low
        heaviest = max(level.buy + level.sell for level in base.footprint)
        poc = next(level for level in base.footprint if level.buy + level.sell == heaviest)
        self.assertAlmostEqual(self.snapshot.base_footprint.poc_location, (poc.price - base.low) / span)
        self.assertAlmostEqual(self.snapshot.base_footprint.delta_over_volume, base.delta / base.volume)
        self.assertAlmostEqual(self.snapshot.leg_out_footprint.delta_over_volume, signal.delta / signal.volume)
        self.assertIsNotNone(self.snapshot.base_footprint.poc_location)
        self.assertGreaterEqual(self.snapshot.base_footprint.poc_location, 0)
        self.assertLessEqual(self.snapshot.base_footprint.poc_location, 1)

        daily = build_series(prefix, "daily", self.clock)[-1]
        weekly = build_series(prefix, "weekly", self.clock)[-1]
        monthly = build_series(prefix, "monthly", self.clock)[-1]
        fraction = (11 * 60 + 15 - (9 * 60 + 15)) / SESSION_MINUTES
        self.assertAlmostEqual(session_fraction(self.clock), fraction)
        self.assertEqual(self.clock, datetime(int(signal.date[:4]), int(signal.date[5:7]), int(signal.date[8:10]), 11, 15))
        self.assertEqual(daily.last_time, "09:15:00")
        self.assertAlmostEqual(
            self.snapshot.daily.volume_over_average,
            (daily.volume / fraction) / daily.average_volume,
        )
        self.assertAlmostEqual(
            self.snapshot.daily.close_ema20_over_atr,
            (daily.close - daily.ema_20) / daily.atr,
        )
        self.assertAlmostEqual(
            self.snapshot.weekly.close_ema20_over_atr,
            (weekly.close - weekly.ema_20) / daily.atr,
        )
        self.assertAlmostEqual(self.snapshot.weekly.true_range_over_atr, weekly.true_range / daily.atr)
        self.assertAlmostEqual(
            self.snapshot.weekly.volume_over_average,
            weekly.volume / weekly.average_volume,
        )
        self.assertAlmostEqual(
            self.snapshot.monthly.close_ema20_over_atr,
            (monthly.close - monthly.ema_20) / daily.atr,
        )
        self.assertIsNone(self.snapshot.retest_footprint)
        self.assertEqual(self.snapshot.order_state, "flat")
        self.assertIsNone(self.snapshot.unrealized_r)
        self.assertIsNone(self.snapshot.equity_over_start)
        self.assertIsNone(self.snapshot.stop_fraction_of_equity)
        self.assertFalse(hasattr(Snapshot, "memory"))
        for price in (signal.open, signal.high, signal.low, signal.close, zone.uoc_high, zone.uoc_low):
            self.assertNotAlmostEqual(self.snapshot.zone_height_over_atr, price, delta=1.0)
            self.assertNotAlmostEqual(self.snapshot.p_accept, price, delta=1.0)

    def test_a_later_bar_changes_nothing(self):
        changed = list(self.bars)
        later = changed[self.zone.end + 1]
        changed[self.zone.end + 1] = dataclasses.replace(
            later,
            close=later.close + 80,
            high=later.high + 80,
            low=later.low - 20,
            footprint=(FootprintLevel(1.0, 40, 1),),
        )
        again = snapshot_at(changed, self.zone, self.clock)
        self.assertTrue(_same(self.snapshot, again))


if __name__ == "__main__":
    unittest.main()
