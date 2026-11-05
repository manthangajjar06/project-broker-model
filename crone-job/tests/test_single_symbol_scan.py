import asyncio
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, patch

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scan_fresh_zones import ScanConfiguration, SymbolScanResult, run


class SingleSymbolScanTests(TestCase):
    def test_run_delegates_to_reusable_symbol_scan_then_writes_result(self):
        configuration = ScanConfiguration()
        result = SymbolScanResult(
            symbol=configuration.symbol,
            scanned_at=pd.Timestamp("2026-11-01 20:00", tz="Asia/Kolkata"),
            scan_start=pd.Timestamp("2024-11-01 20:00", tz="Asia/Kolkata"),
            zones=[],
        )

        with (
            patch("scan_fresh_zones.scan_symbol", new=AsyncMock(return_value=result)) as scan_symbol,
            patch("scan_fresh_zones.write_zones") as write_zones,
        ):
            exit_code = asyncio.run(run(configuration))

        self.assertEqual(exit_code, 0)
        scan_symbol.assert_awaited_once_with(configuration)
        write_zones.assert_called_once_with(result)


if __name__ == "__main__":
    import unittest

    unittest.main()
