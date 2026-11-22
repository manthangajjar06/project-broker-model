"""Step 10. Five hand-built paths, one for each behavior.

A skip of the same candles receives the same label. The policy is not called.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.behavior import (  # noqa: E402
    BASE_NEVER_TOUCHED,
    COMPLETE_STOP,
    SLIGHT_BREACH,
    UNRESOLVED,
    UOC_TOUCH,
    PathCandle,
    TakenTrade,
    label_path,
)


UOC_LOW = 100.0
UOC_HIGH = 110.0
DECISION_CLOSE = 112.0
ATR = 4.0


def _candle(high: float, low: float, close: float) -> PathCandle:
    return PathCandle(high, low, close)


class PathLabels(unittest.TestCase):
    def test_complete_stop_stays_after_a_rally(self):
        candles = [
            _candle(high=101, low=97, close=98),
            _candle(high=120, low=115, close=118),
        ]
        behavior = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR)
        self.assertEqual(behavior.label, COMPLETE_STOP)
        self.assertAlmostEqual(behavior.breach_atr, (UOC_LOW - 97) / ATR)
        self.assertIsNone(behavior.trade_result)
        self._skip_matches(candles, COMPLETE_STOP)

        taken = label_path(
            candles,
            UOC_LOW,
            UOC_HIGH,
            DECISION_CLOSE,
            ATR,
            TakenTrade(result="stop", entry=104.0, placed_stop=99.0, exit_price=99.0),
        )
        self.assertEqual(taken.label, COMPLETE_STOP)
        self.assertEqual(taken.trade_result, "stop")
        self.assertAlmostEqual(taken.realized_r, (99.0 - 104.0) / (104.0 - 99.0))

    def test_slight_breach_then_reversal(self):
        candles = [
            _candle(high=102, low=99.5, close=101),
            _candle(high=112, low=108, close=111),
        ]
        behavior = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR)
        self.assertEqual(behavior.label, SLIGHT_BREACH)
        self._skip_matches(candles, SLIGHT_BREACH)

    def test_uoc_touch_and_bounce(self):
        candles = [
            _candle(high=112, low=105, close=108),
            _candle(high=112, low=109, close=111),
        ]
        behavior = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR)
        self.assertEqual(behavior.label, UOC_TOUCH)
        self._skip_matches(candles, UOC_TOUCH)

    def test_down_but_the_base_is_never_touched(self):
        candles = [
            _candle(high=113, low=111, close=111.5),
            _candle(high=114, low=112.5, close=113),
        ]
        behavior = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR)
        self.assertEqual(behavior.label, BASE_NEVER_TOUCHED)
        self._skip_matches(candles, BASE_NEVER_TOUCHED)

    def test_unresolved_when_none_of_the_four_match(self):
        candles = [
            _candle(high=116, low=114, close=115),
            _candle(high=116, low=114.5, close=115),
        ]
        behavior = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR)
        self.assertEqual(behavior.label, UNRESOLVED)
        self._skip_matches(candles, UNRESOLVED)

    def _skip_matches(self, candles, label: str) -> None:
        skipped = label_path(candles, UOC_LOW, UOC_HIGH, DECISION_CLOSE, ATR, trade=None)
        self.assertEqual(skipped.label, label)
        self.assertIsNone(skipped.trade_result)
        self.assertIsNone(skipped.realized_r)


if __name__ == "__main__":
    unittest.main()
