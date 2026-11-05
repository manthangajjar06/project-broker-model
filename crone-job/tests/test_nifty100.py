import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nifty100 import EXPECTED_CONSTITUENT_COUNT, ConstituentListError, parse_constituent_symbols


def csv_payload(symbols: list[str], header: str = "Symbol,Company Name") -> bytes:
    rows = [header, *[f"{symbol},Example company" for symbol in symbols]]
    return ("\n".join(rows) + "\n").encode("utf-8")


class Nifty100ConstituentTests(unittest.TestCase):
    def test_parses_exactly_one_hundred_unique_symbols_in_source_order(self):
        symbols = [f"STOCK{number:03d}" for number in range(EXPECTED_CONSTITUENT_COUNT)]
        result = parse_constituent_symbols(csv_payload(symbols))
        self.assertEqual(result, tuple(symbols))

    def test_accepts_utf8_bom_and_case_insensitive_symbol_header(self):
        symbols = [f"STOCK{number:03d}" for number in range(EXPECTED_CONSTITUENT_COUNT)]
        payload = csv_payload(symbols, header=" symbol ,Company Name")
        self.assertEqual(parse_constituent_symbols(b"\xef\xbb\xbf" + payload)[0], "STOCK000")

    def test_rejects_missing_symbol_column(self):
        payload = csv_payload([f"STOCK{number:03d}" for number in range(EXPECTED_CONSTITUENT_COUNT)], header="Ticker,Company Name")
        with self.assertRaisesRegex(ConstituentListError, "no Symbol column"):
            parse_constituent_symbols(payload)

    def test_rejects_duplicate_symbol(self):
        symbols = [f"STOCK{number:03d}" for number in range(EXPECTED_CONSTITUENT_COUNT)]
        symbols[-1] = symbols[0]
        with self.assertRaisesRegex(ConstituentListError, "duplicate symbol"):
            parse_constituent_symbols(csv_payload(symbols))

    def test_rejects_an_unexpected_constituent_count(self):
        payload = csv_payload([f"STOCK{number:03d}" for number in range(EXPECTED_CONSTITUENT_COUNT - 1)])
        with self.assertRaisesRegex(ConstituentListError, "Expected exactly 100"):
            parse_constituent_symbols(payload)


if __name__ == "__main__":
    unittest.main()
