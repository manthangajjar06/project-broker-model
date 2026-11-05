import asyncio
import sys
from pathlib import Path
import unittest

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch_scan import scan_configurations
from scan_fresh_zones import ScanConfiguration, SymbolScanResult


def configuration(symbol: str) -> ScanConfiguration:
    return ScanConfiguration(symbol=symbol, chart_url=f"https://example.test/{symbol}")


def result_for(symbol: str) -> SymbolScanResult:
    return SymbolScanResult(
        symbol=symbol,
        scanned_at=pd.Timestamp("2026-11-01 20:00", tz="Asia/Kolkata"),
        scan_start=pd.Timestamp("2024-11-01 20:00", tz="Asia/Kolkata"),
        zones=[],
    )


class BatchScanTests(unittest.TestCase):
    def test_a_failure_does_not_stop_later_symbol_scans(self):
        first = configuration("NSE:AAA")
        failed = configuration("NSE:BBB")
        last = configuration("NSE:CCC")
        calls: list[str] = []

        async def scanner(item: ScanConfiguration) -> SymbolScanResult:
            calls.append(item.symbol)
            if item.symbol == failed.symbol:
                raise RuntimeError("Kite chart timed out")
            return result_for(item.symbol)

        batch = asyncio.run(scan_configurations([first, failed, last], scanner=scanner))

        self.assertEqual(calls, ["NSE:AAA", "NSE:BBB", "NSE:CCC"])
        self.assertEqual([item.symbol for item in batch.successful_scans], ["NSE:AAA", "NSE:CCC"])
        self.assertEqual(len(batch.failures), 1)
        self.assertEqual(batch.failures[0].symbol, "NSE:BBB")
        self.assertEqual(batch.failures[0].error_type, "RuntimeError")
        self.assertEqual(batch.failures[0].message, "Kite chart timed out")

    def test_a_mismatched_result_is_recorded_as_a_failure(self):
        requested = configuration("NSE:AAA")

        async def scanner(_: ScanConfiguration) -> SymbolScanResult:
            return result_for("NSE:WRONG")

        batch = asyncio.run(scan_configurations([requested], scanner=scanner))

        self.assertEqual(batch.successful_scans, ())
        self.assertEqual(batch.failures[0].error_type, "SymbolMismatchError")
        self.assertIn("NSE:WRONG", batch.failures[0].message)


if __name__ == "__main__":
    unittest.main()
