"""Plan 2 Step A1. Engineered features, labels, and no future leak."""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.behavior import PATH_BARS, PathCandle, label_path  # noqa: E402
from Model.clock import decision_clock, known_clock  # noqa: E402
from Model.fill import STOP, TARGET, ClosedCandle  # noqa: E402
from Model.higher import HigherBook  # noqa: E402
from Model.htf_encode import encode_htf, htf_feature_names, htf_width  # noqa: E402
from Model.load import FootprintLevel, csv_path, load_bars  # noqa: E402
from Model.memory import Memory  # noqa: E402
from Model.outcome_dataset import (  # noqa: E402
    TRAIN_LAST_YEAR,
    feature_names,
    feature_width,
    measure_locked_plan,
    rows_for_symbol,
    split_of,
    y_bounce_of,
)
from Model.predict import load_frozen_model  # noqa: E402
from Model.score import accepted_zones, score_zones  # noqa: E402
from Model.snapshot import snapshot_at  # noqa: E402
from entry import required_plan  # noqa: E402


def _resolve_stop(hit):
    return STOP


class FeatureContract(unittest.TestCase):
    def test_feature_width_matches_names(self):
        names = feature_names()
        self.assertEqual(len(names), feature_width())
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(htf_width(), len(htf_feature_names()))
        self.assertTrue(any(name.startswith("htf_daily_") for name in names))
        self.assertTrue(any(name.startswith("mem_") for name in names))


class LabelRules(unittest.TestCase):
    def test_y_bounce_is_target_only(self):
        self.assertEqual(y_bounce_of(TARGET), 1)
        self.assertEqual(y_bounce_of(STOP), 0)
        self.assertEqual(y_bounce_of("time_stop"), 0)
        self.assertEqual(y_bounce_of("no_fill"), 0)
        self.assertEqual(y_bounce_of(None), 0)

    def test_split_years_are_frozen(self):
        self.assertEqual(split_of(TRAIN_LAST_YEAR), "train")
        self.assertEqual(split_of(2018), "train")
        self.assertEqual(split_of(2022), "val")
        self.assertEqual(split_of(2023), "val")
        self.assertEqual(split_of(2024), "test")
        self.assertEqual(split_of(2026), "test")


class RelianceOutcome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(csv_path("RELIANCE"))
        cls.model = load_frozen_model()
        higher = HigherBook()
        higher.run_model("RELIANCE", cls.bars)
        cls.sample = None
        try:
            for scored in accepted_zones(score_zones(cls.bars, cls.model)):
                plan = required_plan(cls.bars, scored.zone, scored.probability)
                clock = known_clock(cls.bars[scored.zone.end])
                if plan is None or clock is None:
                    continue
                if not higher.allows_decision(clock):
                    continue
                if not (plan.stop < plan.entry):
                    continue
                if clock.year > TRAIN_LAST_YEAR:
                    continue
                cls.sample = (scored.zone, scored.probability, plan, clock)
                break
        finally:
            higher.close_stock()
        if cls.sample is None:
            raise unittest.SkipTest("no armable Reliance training zone found")

    def test_later_candle_does_not_change_features(self):
        zone, probability, plan, clock = self.sample
        memory = Memory(())
        from Model.outcome_dataset import features_at_decision

        before, _ = features_at_decision(self.bars, zone, plan, clock, memory)
        changed = list(self.bars)
        later = changed[zone.end + 1]
        changed[zone.end + 1] = dataclasses.replace(
            later,
            close=later.close + 90,
            high=later.high + 90,
            low=later.low - 25,
            footprint=(FootprintLevel(1.0, 50, 1),),
        )
        after, _ = features_at_decision(changed, zone, plan, clock, memory)
        self.assertEqual(before, after)
        self.assertEqual(encode_htf(self.bars, clock), encode_htf(changed, clock))
        self.assertTrue(
            all(
                left == right
                for left, right in zip(
                    snapshot_at(self.bars, zone, clock).features,
                    snapshot_at(changed, zone, clock).features,
                )
            )
        )

    def test_labels_match_fill_and_behavior_rules(self):
        zone, probability, plan, clock = self.sample
        y_bounce, behavior, trade_result, realized_r, resolved_at = measure_locked_plan(
            self.bars,
            zone,
            plan,
            "RELIANCE",
            _resolve_stop,
        )
        self.assertIn(y_bounce, (0, 1))
        self.assertIsNotNone(resolved_at)
        self.assertGreaterEqual(resolved_at, clock)

        signal = self.bars[zone.end]
        later = self.bars[zone.end + 1 : zone.end + 1 + PATH_BARS]
        path = [PathCandle(bar.high, bar.low, bar.close) for bar in later]
        expected = label_path(path, zone.uoc_low, zone.uoc_high, signal.close, signal.atr_14)
        self.assertEqual(behavior, expected.label)
        if y_bounce == 1:
            self.assertEqual(trade_result, "target")
        if trade_result == "stop":
            self.assertEqual(y_bounce, 0)

    def test_training_rows_have_no_decision_year_from_2022(self):
        rows = rows_for_symbol("RELIANCE", resolve=_resolve_stop)
        self.assertGreater(len(rows), 0)
        train = [row for row in rows if row.split == "train"]
        self.assertGreater(len(train), 0)
        for row in train:
            self.assertLessEqual(row.decided_at.year, TRAIN_LAST_YEAR)
            self.assertEqual(len(row.features), feature_width())
            self.assertEqual(row.feature_names, feature_names())
        for row in rows:
            if row.decided_at.year >= 2022:
                self.assertIn(row.split, ("val", "test"))
            if row.decided_at.year >= 2024:
                self.assertEqual(row.split, "test")


if __name__ == "__main__":
    unittest.main()
