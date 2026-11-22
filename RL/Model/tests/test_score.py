"""Step 4. Reliance probabilities match the chart to about 1e-6.

The accepted zones are the one-per-base set whose label is accepted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.load import csv_path, load_bars  # noqa: E402
from Model.predict import score_label  # noqa: E402
from Model.score import accepted_zones, score_zones  # noqa: E402
from Model.zones import keep_one  # noqa: E402


CHART = Path(__file__).resolve().parent / "chart_zones.mjs"
TOLERANCE = 1e-6


class Labels(unittest.TestCase):
    def test_the_three_labels(self):
        self.assertEqual(score_label(0.55), "accepted")
        self.assertEqual(score_label(0.90), "accepted")
        self.assertEqual(score_label(0.45), "rejected")
        self.assertEqual(score_label(0.10), "rejected")
        self.assertEqual(score_label(0.50), "uncertain")
        self.assertEqual(score_label(0.549), "uncertain")


class RelianceScore(unittest.TestCase):
    def test_probabilities_match_the_chart(self):
        bars = load_bars(csv_path("RELIANCE"))
        completed = subprocess.run(
            ["node", str(CHART)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        chart = json.loads(completed.stdout)
        scored = score_zones(bars)
        self.assertEqual(len(scored), len(chart["zones"]))
        self.assertGreater(len(scored), 0)

        for index, (item, expected) in enumerate(zip(scored, chart["zones"])):
            where = f"zone {index} {expected['pattern']} {expected['startDate']} {expected['startClock']}"
            self.assertEqual(item.zone.pattern, expected["pattern"], where)
            self.assertEqual(item.zone.leg_out_mode, expected["legOutMode"], where)
            self.assertEqual(item.zone.start, expected["start"], where)
            self.assertEqual(item.zone.end, expected["end"], where)
            self.assertAlmostEqual(item.probability, expected["probability"], delta=TOLERANCE, msg=where)
            self.assertEqual(item.label, expected["label"], where)
            self.assertAlmostEqual(item.entry, expected["entry"], delta=TOLERANCE, msg=where)
            self.assertEqual(item.entry_warning, expected["warning"], where)

        ours = keep_one([item.zone for item in scored], [item.probability for item in scored])
        chart_kept = keep_one(
            [item.zone for item in scored],
            [row["probability"] for row in chart["zones"]],
        )
        key = lambda zone: (zone.pattern, zone.start, zone.end, zone.leg_out_mode)
        self.assertEqual([key(zone) for zone in ours], [key(zone) for zone in chart_kept])

        chart_label = {key_of: row["label"] for key_of, row in zip(map(key, (item.zone for item in scored)), chart["zones"])}
        chart_accepted = {key(zone) for zone in chart_kept if chart_label[key(zone)] == "accepted"}
        actionable = accepted_zones(scored)
        self.assertTrue(all(item.label == "accepted" for item in actionable))
        self.assertEqual({key(item.zone) for item in actionable}, chart_accepted)
        self.assertGreater(len(actionable), 0)
