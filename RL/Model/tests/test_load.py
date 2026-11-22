"""Step 1. Reliance loads in time order, with the plan's columns.

A footprint cell splits into price, buy, and sell. Empty early indicator
cells stay empty. A written zero stays zero.
"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.load import (  # noqa: E402
    BLANKABLE,
    COLUMNS,
    REQUIRED_NUMBERS,
    Bar,
    FootprintLevel,
    LoadError,
    csv_path,
    load_bars,
)


def _levels(text: str) -> list[tuple[float, float, float]]:
    raw = text.strip()
    if not raw:
        return []
    levels = []
    for part in raw.split(";"):
        price_text, sides = part.split("=")
        buy_text, sell_text = sides.split("/")
        levels.append((float(price_text), float(buy_text), float(sell_text)))
    return levels


def _csv_text(rows: list[dict[str, str]]) -> str:
    lines = [",".join(COLUMNS)]
    for row in rows:
        lines.append(",".join(row.get(name, "") for name in COLUMNS))
    return "\n".join(lines) + "\n"


class RelianceLoad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = csv_path("RELIANCE")
        cls.bars = load_bars(cls.path)
        with cls.path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            cls.header = tuple(cell.strip() for cell in next(reader))
            cls.raw_rows = [row for row in reader if any(cell.strip() for cell in row)]

    def test_column_set_matches_the_plan(self):
        self.assertEqual(self.header, COLUMNS)
        self.assertEqual(len(self.bars), len(self.raw_rows))
        self.assertGreater(len(self.bars), 0)
        self.assertIsInstance(self.bars[0], Bar)

    def test_reliance_loads_in_time_order(self):
        self.assertEqual(self.bars[0].date, "2015-02-02")
        self.assertEqual(self.bars[0].time, "09:15:00")
        self.assertEqual(self.bars[-1].date, "2026-11-13")
        self.assertEqual(self.bars[-1].time, "13:15:00")
        opens = [bar.open_at() for bar in self.bars]
        for earlier, later in zip(opens, opens[1:]):
            self.assertLess(earlier, later)

    def test_footprint_splits_into_price_buy_and_sell(self):
        first = self.bars[0].footprint
        self.assertEqual(first[0], FootprintLevel(215.25, 7858, 39828))
        self.assertEqual(first[1], FootprintLevel(215.50, 166072, 302920))
        session = next(bar for bar in self.bars if bar.date == "2015-02-02" and bar.time == "15:15:00")
        self.assertIn(FootprintLevel(214.00, 0.0, 80890), session.footprint)
        for bar, row in zip(self.bars, self.raw_rows):
            expected = _levels(row[-1])
            actual = [(level.price, level.buy, level.sell) for level in bar.footprint]
            self.assertEqual(actual, expected)

    def test_empty_indicator_cells_stay_empty(self):
        first = self.bars[0]
        self.assertIsNone(first.atr_14)
        self.assertIsNone(first.datr_14)
        self.assertIsNone(first.avg_volume_14d)
        self.assertIsNone(first.ema_20)
        self.assertIsNone(first.ema_50)
        for bar, row in zip(self.bars, self.raw_rows):
            raw = dict(zip(COLUMNS, row))
            for name in BLANKABLE:
                loaded = getattr(bar, name)
                if raw[name].strip() == "":
                    self.assertIsNone(loaded)
                else:
                    self.assertEqual(loaded, float(raw[name]))
            for name in REQUIRED_NUMBERS:
                self.assertEqual(getattr(bar, name), float(raw[name]))

    def test_a_written_zero_stays_zero(self):
        wick = next(bar for bar in self.bars if bar.date == "2026-11-06" and bar.time == "09:15:00")
        self.assertEqual(wick.lower_wick_pct, 0.0)
        body = next(bar for bar in self.bars if bar.date == "2026-11-13" and bar.time == "11:15:00")
        self.assertEqual(body.body_pct, 0.0)
        odd = next(bar for bar in self.bars if bar.date == "2026-11-08" and bar.time == "14:20:00")
        self.assertEqual(odd.interval, "2hour")
        self.assertGreater(len(odd.footprint), 0)


class BlankCells(unittest.TestCase):
    def test_blank_stays_blank_and_zero_stays_zero(self):
        text = _csv_text(
            [
                {
                    "interval": "2hour",
                    "date": "2015-02-02",
                    "time": "09:15:00",
                    "open": "1",
                    "high": "2",
                    "low": "0.5",
                    "close": "1.5",
                    "volume": "10",
                    "upper_wick_pct": "0.0000",
                    "lower_wick_pct": "0",
                    "body_pct": "50",
                    "tr": "1",
                    "buy_volume": "3",
                    "sell_volume": "7",
                    "delta": "-4",
                    "footprint": "1.00=0/5",
                },
                {
                    "interval": "2hour",
                    "date": "2015-02-02",
                    "time": "11:15:00",
                    "open": "1.5",
                    "high": "2",
                    "low": "1",
                    "close": "1.5",
                    "volume": "0",
                    "upper_wick_pct": "1",
                    "lower_wick_pct": "1",
                    "body_pct": "1",
                    "tr": "1",
                    "atr_14": "0.0000",
                    "datr_14": "2",
                    "avg_volume_14d": "3",
                    "ema_20": "4",
                    "ema_50": "5",
                    "buy_volume": "0",
                    "sell_volume": "0",
                    "delta": "0",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "NSE_SAMPLE_2hour.csv"
            path.write_text(text, encoding="utf-8")
            bars = load_bars(path)
        self.assertIsNone(bars[0].atr_14)
        self.assertIsNone(bars[0].datr_14)
        self.assertIsNone(bars[0].avg_volume_14d)
        self.assertIsNone(bars[0].ema_20)
        self.assertIsNone(bars[0].ema_50)
        self.assertEqual(bars[0].lower_wick_pct, 0.0)
        self.assertEqual(bars[0].upper_wick_pct, 0.0)
        self.assertEqual(bars[0].footprint, (FootprintLevel(1.0, 0.0, 5.0),))
        self.assertEqual(bars[1].volume, 0.0)
        self.assertEqual(bars[1].atr_14, 0.0)
        self.assertEqual(bars[1].buy_volume, 0.0)
        self.assertEqual(bars[1].delta, 0.0)
        self.assertEqual(bars[1].footprint, ())

    def test_a_different_column_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "NSE_BAD_2hour.csv"
            path.write_text("date,time,open\n2015-02-02,09:15:00,1\n", encoding="utf-8")
            with self.assertRaises(LoadError):
                load_bars(path)


if __name__ == "__main__":
    unittest.main()
