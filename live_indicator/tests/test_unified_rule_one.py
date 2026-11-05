import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from zone_tracker_v2 import calculate_entry


class UnifiedRuleOneTests(unittest.TestCase):
    def test_no_lower_wick_entry_is_leg_out_open(self):
        entry = calculate_entry(
            pd.Series({"open": 100, "high": 105, "low": 99, "close": 103}),
            pd.Series({"open": 104, "high": 112, "low": 104, "close": 110}),
            datr=20,
        )
        self.assertEqual(entry.base_entry, 104)
        self.assertEqual(entry.final_entry, 104)


if __name__ == "__main__":
    unittest.main()
