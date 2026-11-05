import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kite_instruments import chart_url, parse_equity_tokens

CSV = """instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
1270529,4955,ICICIBANK,ICICI BANK,0,,0,0.05,1,EQ,NSE,NSE
519937,2031,M&M,MAHINDRA,0,,0,0.05,1,EQ,NSE,NSE
999,1,ICICIBANK-N1,ICICI NCD,0,,0,0.01,1,N1,NSE,NSE
"""


class InstrumentTests(unittest.TestCase):
    def test_only_equities_are_mapped(self):
        tokens = parse_equity_tokens(CSV)
        self.assertEqual(tokens, {"ICICIBANK": 1270529, "M&M": 519937})

    def test_url_matches_known_good_and_encodes_ampersand(self):
        self.assertEqual(chart_url("ICICIBANK", 1270529), "https://kite.zerodha.com/chart/web/tvc/NSE/ICICIBANK/1270529")
        self.assertIn("M%26M", chart_url("M&M", 519937))


if __name__ == "__main__":
    unittest.main()
