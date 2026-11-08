import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.format_zones import format_symbol_block, pretty_timestamp


class FormatZonesTests(unittest.TestCase):
    def test_formats_multiline_html_zone_card(self):
        zone = {
            "pattern_type": "DBR",
            "leg_out_mode": "SINGLE",
            "formed_at": "2026-02-19T15:15:00+05:30",
            "zone_low": 5695.0,
            "zone_high": 5718.0,
            "entry": {"final_entry": 5718.0},
            "ml": {"label": "accepted", "p_accept": 0.9672},
        }
        text = format_symbol_block("NSE:ABB", [zone])
        self.assertIn("<b>NSE:ABB</b>", text)
        self.assertIn("<b>#1 DBR · SINGLE</b>", text)
        self.assertIn("Formed: 19 Feb 2026, 15:15", text)
        self.assertIn("<code>5695.00 – 5718.00</code>", text)
        self.assertIn("<code>5718.00</code>", text)
        self.assertIn("<b>ACCEPTED</b> (96.72%)", text)
        self.assertNotIn("|", text)

    def test_pretty_timestamp_falls_back_for_odd_values(self):
        self.assertEqual(pretty_timestamp("not-a-date"), "not-a-date")
        self.assertEqual(pretty_timestamp(None), "?")


if __name__ == "__main__":
    unittest.main()
