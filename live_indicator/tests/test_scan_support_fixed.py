import sys
from pathlib import Path
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from scan_support_fixed import _entry, build_zones, drop_forming_candle, prepare_dataframe


class ScanSupportFixedTests(unittest.TestCase):
    def test_forming_last_candle_is_excluded(self):
        dataframe = pd.DataFrame([
            {"timestamp": "2026-10-28 09:15", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
            {"timestamp": "2026-10-28 09:20", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
            {"timestamp": "2026-10-28 09:25", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1},
        ])
        dataframe["timestamp"] = pd.to_datetime(dataframe["timestamp"])
        result = drop_forming_candle(dataframe, now=pd.Timestamp("2026-10-28 09:27"))
        self.assertEqual(len(result), 2)

    def test_missing_datr_never_claims_buffer_was_applied(self):
        uoc = pd.Series({"open": 100, "high": 106, "low": 99, "close": 104})
        leg_out = pd.Series({"open": 103, "high": 112, "low": 102, "close": 110})
        entry = _entry(uoc, leg_out, None)
        self.assertEqual(entry.final_entry, 104)
        self.assertFalse(entry.buffer_applied)
        self.assertEqual(entry.warning, "datr_unavailable")

    def test_single_and_super_get_distinct_ids_but_shared_visual_id(self):
        dataframe = pd.DataFrame([
            {"timestamp": "2026-10-01 09:15", "open": 110, "high": 111, "low": 100, "close": 101, "volume": 1},
            {"timestamp": "2026-10-01 09:20", "open": 101, "high": 104, "low": 99, "close": 103, "volume": 1},
            {"timestamp": "2026-10-01 09:25", "open": 103, "high": 115, "low": 102, "close": 114, "volume": 1},
            {"timestamp": "2026-10-01 09:30", "open": 114, "high": 116, "low": 113, "close": 115, "volume": 1},
            {"timestamp": "2026-10-01 09:35", "open": 115, "high": 117, "low": 114, "close": 116, "volume": 1},
        ])
        dataframe["timestamp"] = pd.to_datetime(dataframe["timestamp"])
        candidates = [
            {"pattern_type": "DBR", "leg_out_mode": "SINGLE", "start_index": 0, "end_index": 2},
            {"pattern_type": "DBR", "leg_out_mode": "SUPER", "start_index": 0, "end_index": 4},
        ]
        zones = build_zones(dataframe, candidates, "NSE:TEST")
        self.assertNotEqual(zones[0]["zone_id"], zones[1]["zone_id"])
        self.assertEqual(zones[0]["visual_id"], zones[1]["visual_id"])

    def test_invalid_duplicate_candles_are_dropped_and_latest_is_kept(self):
        candles = [
            {"timestamp": 1_700_000_000_000, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"timestamp": 1_700_000_000_000, "open": 100, "high": 105, "low": 99, "close": 104, "volume": 1},
            {"timestamp": 1_700_000_300_000, "open": 100, "high": 98, "low": 99, "close": 100, "volume": 1},
            {"timestamp": 1_700_000_600_000, "open": 104, "high": 106, "low": 103, "close": 105, "volume": 1},
            {"timestamp": 1_700_000_900_000, "open": 105, "high": 107, "low": 104, "close": 106, "volume": 1},
        ]
        dataframe, dropped = prepare_dataframe(candles)
        self.assertEqual(dropped, 1)
        self.assertEqual(float(dataframe.iloc[0]["close"]), 104)


if __name__ == "__main__":
    unittest.main()
