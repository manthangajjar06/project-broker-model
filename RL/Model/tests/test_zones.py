"""Step 3. Reliance zone geometry matches the chart.

Pattern, start, end, and the UOC high and low. The fresh-or-worked walk is
not part of the zone. Probability is not used to drop a candidate.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.load import Bar, csv_path, load_bars  # noqa: E402
from Model.zones import Zone, find_zones, keep_one  # noqa: E402


CHART = Path(__file__).resolve().parent / "chart_zones.mjs"


def _bar(date: str, clock: str, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        interval="2hour",
        date=date,
        time=clock,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1,
        upper_wick_pct=0,
        lower_wick_pct=0,
        body_pct=0,
        tr=high - low,
        atr_14=None,
        datr_14=None,
        avg_volume_14d=None,
        ema_20=None,
        ema_50=None,
        buy_volume=0,
        sell_volume=0,
        delta=0,
        footprint=(),
    )


def _zone(pattern: str, mode: str, start: int) -> Zone:
    end = start + (4 if mode == "SUPER" else 2)
    return Zone(pattern, mode, start, end, 1.0, 2.0, metrics=_metrics())


def _metrics():
    from Model.zones import ZoneMetrics

    return ZoneMetrics(1, 1, 1, "Green", False, 0, 1, None, 1)


class KeepOne(unittest.TestCase):
    def test_higher_probability_wins_and_super_wins_a_tie(self):
        zones = [
            _zone("DBR", "SINGLE", 0),
            _zone("DBR", "SUPER", 0),
            _zone("RBR", "SINGLE", 0),
            _zone("DBR", "SINGLE", 5),
            _zone("DBR", "SUPER", 5),
            _zone("DBR", "SINGLE", 5),
        ]
        kept = keep_one(zones, [0.50, 0.50, 0.90, 0.20, 0.20, 0.30])
        self.assertEqual([(zone.pattern, zone.leg_out_mode, zone.start) for zone in kept], [
            ("DBR", "SUPER", 0),
            ("RBR", "SINGLE", 0),
            ("DBR", "SINGLE", 5),
        ])


class RelianceZones(unittest.TestCase):
    def test_geometry_matches_the_chart(self):
        bars = load_bars(csv_path("RELIANCE"))
        completed = subprocess.run(
            ["node", str(CHART)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        chart = json.loads(completed.stdout)
        self.assertEqual(chart["bars"], len(bars))
        self.assertEqual(chart["first"], {"date": bars[0].date, "clock": bars[0].time[:5]})
        self.assertEqual(chart["last"], {"date": bars[-1].date, "clock": bars[-1].time[:5]})

        zones = find_zones(bars)
        self.assertEqual(len(zones), len(chart["zones"]))
        for zone, expected in zip(zones, chart["zones"]):
            self.assertEqual(zone.pattern, expected["pattern"])
            self.assertEqual(zone.leg_out_mode, expected["legOutMode"])
            self.assertEqual(zone.start, expected["start"])
            self.assertEqual(zone.end, expected["end"])
            self.assertEqual(bars[zone.start].date, expected["startDate"])
            self.assertEqual(bars[zone.start].time[:5], expected["startClock"])
            self.assertEqual(bars[zone.end].date, expected["endDate"])
            self.assertEqual(bars[zone.end].time[:5], expected["endClock"])
            self.assertEqual(zone.uoc_low, expected["uocLow"])
            self.assertEqual(zone.uoc_high, expected["uocHigh"])
            base = bars[zone.start + 1]
            self.assertEqual(zone.uoc_low, base.low)
            self.assertEqual(zone.uoc_high, base.high)


if __name__ == "__main__":
    unittest.main()
