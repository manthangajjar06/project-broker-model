"""Step 15. The training years stop at 2021, and a checkpoint is kept only
when the 80–90% calls land in that range and beat the baseline.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.train import (  # noqa: E402
    BEHAVIOR_LOSS_WEIGHT,
    YearScore,
    baseline_average_r,
    keep_checkpoint,
    split_for,
    training_log_is_clean,
)


class TrainingContract(unittest.TestCase):
    def test_the_behavior_weight_is_locked_at_one_tenth(self):
        self.assertEqual(BEHAVIOR_LOSS_WEIGHT, 0.1)

    def test_a_training_log_has_no_decision_from_2024(self):
        clocks = [
            datetime(2018, 6, 1, 11, 15),
            datetime(2021, 12, 31, 15, 30),
        ]
        self.assertTrue(training_log_is_clean(clocks))
        self.assertEqual(split_for(datetime(2022, 1, 3, 11, 15)), "validation")
        self.assertEqual(split_for(datetime(2024, 1, 2, 11, 15)), "test")
        self.assertFalse(training_log_is_clean(clocks + [datetime(2024, 1, 2, 11, 15)]))

    def test_a_checkpoint_outside_the_band_is_not_kept(self):
        report = Path(__file__).resolve().parents[1].joinpath("baseline_report.txt").read_text(encoding="utf-8")
        inside = [
            YearScore(2022, 0.85, baseline_average_r(2022, report) + 0.1),
            YearScore(2023, 0.85, baseline_average_r(2023, report) + 0.1),
        ]
        self.assertTrue(keep_checkpoint(inside, 0.1, report))
        low_rate = [YearScore(2022, 0.50, 1.0), YearScore(2023, 0.85, 1.0)]
        self.assertFalse(keep_checkpoint(low_rate, 0.1, report))
        weak_r = [
            YearScore(2022, 0.85, baseline_average_r(2022, report)),
            YearScore(2023, 0.85, 1.0),
        ]
        self.assertFalse(keep_checkpoint(weak_r, 0.1, report))
        self.assertFalse(keep_checkpoint(inside, 0.2, report))

    def test_score_validation_trades_uses_the_eighty_ninety_band(self):
        from Model.broker_env import TradeLog
        from Model.train import score_validation_trades

        trades = [
            TradeLog("RELIANCE", datetime(2022, 3, 1, 11, 15), 0.85, "target", 1.2, "uoc_touch"),
            TradeLog("RELIANCE", datetime(2022, 4, 1, 11, 15), 0.85, "stop", -1.0, "complete_stop"),
            TradeLog("RELIANCE", datetime(2022, 5, 1, 11, 15), 0.50, "target", 2.0, "uoc_touch"),
            TradeLog("TCS", datetime(2023, 3, 1, 11, 15), 0.82, "target", 0.5, "uoc_touch"),
        ]
        scores = {row.year: row for row in score_validation_trades(trades)}
        self.assertAlmostEqual(scores[2022].bounce_rate, 0.5)
        self.assertEqual(scores[2022].trade_count, 2)
        self.assertAlmostEqual(scores[2023].bounce_rate, 1.0)
        self.assertEqual(scores[2023].trade_count, 1)


class TrainingSmoke(unittest.TestCase):
    def test_the_policy_takes_one_masked_step(self):
        from Model.broker_env import build_offers, load_names
        from Model.train import build_model, make_env

        names = load_names(["RELIANCE"])
        offers = build_offers(names, 2018, 2018)
        self.assertGreater(len(offers), 0)
        env = make_env(names, 2018, 2018, offers=offers, ask_when_both=False)
        model = build_model(env)
        obs, _ = env.reset()
        mask = env.action_masks()
        self.assertTrue(mask.any())
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        obs2, reward, done, truncated, info = env.step(int(action))
        self.assertEqual(obs2.shape, obs.shape)
        self.assertIn("action_mask", info)


if __name__ == "__main__":
    unittest.main()
