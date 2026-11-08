import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run_nifty100
from batch_scan import BatchScanResult


class TelegramZoneDetailBlocksTests(unittest.TestCase):
    def test_builds_html_blocks_per_symbol(self):
        zone = {
            "pattern_type": "DBR",
            "leg_out_mode": "SINGLE",
            "formed_at": "2026-02-19T15:15:00+05:30",
            "zone_low": 5695.0,
            "zone_high": 5718.0,
            "entry": {"final_entry": 5718.0},
            "ml": {"label": "accepted", "p_accept": 0.9672},
        }
        with_zones = Mock(symbol="NSE:ABB", zones=[zone])
        without_zones = Mock(symbol="NSE:BBB", zones=[])
        failure = Mock(symbol="NSE:CCC", error_type="RuntimeError", message="boom")
        batch = BatchScanResult(
            started_at=Mock(),
            completed_at=Mock(),
            successful_scans=(with_zones, without_zones),
            failures=(failure,),
        )

        blocks = run_nifty100.telegram_zone_detail_blocks(batch, ["GONE"])
        joined = "\n\n".join(blocks)

        self.assertIn("<b>NSE:ABB</b>", joined)
        self.assertIn("Formed: 19 Feb 2026, 15:15", joined)
        self.assertIn("<b>ACCEPTED</b> (96.72%)", joined)
        self.assertNotIn("NSE:BBB", joined)
        self.assertIn("<b>Failures</b>", joined)
        self.assertIn("NSE:CCC", joined)
        self.assertIn("<b>No Kite token</b>", joined)
        self.assertIn("GONE", joined)
        self.assertNotIn("Details:", joined)


if __name__ == "__main__":
    unittest.main()
