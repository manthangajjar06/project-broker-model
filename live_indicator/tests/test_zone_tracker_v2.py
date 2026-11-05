import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from zone_tracker_v2 import calculate_entry


class ZoneTrackerV2Tests(unittest.TestCase):
    def test_no_lower_wick_uses_leg_out_open_without_buffer(self):
        uoc = pd.Series({"open": 100, "high": 106, "low": 99, "close": 104})
        leg_out = pd.Series({"open": 105, "high": 114, "low": 105, "close": 112})
        entry = calculate_entry(uoc, leg_out, datr=10)
        self.assertEqual((entry.base_entry, entry.final_entry), (105, 105))
        self.assertFalse(entry.buffer_applied)
        self.assertEqual(entry.rule, "rule_1_no_leg_out_lower_wick")


if __name__ == "__main__":
    unittest.main()
