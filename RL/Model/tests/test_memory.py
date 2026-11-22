"""Step 12. A later decision sees only records that have already resolved.

A Reliance decision in 2018 can see a resolved 2016 record. It cannot see
a 2019 record. Rebuilding the memory reproduces the same neighbors.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.behavior import COMPLETE_STOP, UOC_TOUCH  # noqa: E402
from Model.clock import known_clock  # noqa: E402
from Model.load import csv_path, load_bars  # noqa: E402
from Model.memory import (  # noqa: E402
    NEIGHBOR_COUNT,
    Memory,
    Record,
    context_of,
    resolution_clock,
)
from Model.score import accepted_zones, score_zones  # noqa: E402
from Model.snapshot import snapshot_at  # noqa: E402
from entry import required_plan  # noqa: E402


def _record(symbol: str, resolved: datetime, value: float, behavior: str = COMPLETE_STOP, realized_r: float | None = None) -> Record:
    return Record(
        symbol=symbol,
        decided_at=resolved,
        resolved_at=resolved,
        context=(value,),
        behavior=behavior,
        trade_result=None if realized_r is None else "stop",
        realized_r=realized_r,
    )


class VisibleRecords(unittest.TestCase):
    def test_a_record_is_hidden_until_its_outcome_time(self):
        early = _record("EARLY", datetime(2016, 6, 1, 11, 15), 0.0)
        same_clock = _record("SAME", datetime(2018, 3, 1, 11, 15), 1.0)
        later = _record("LATER", datetime(2018, 3, 1, 13, 15), 0.0)
        memory = Memory((later, early, same_clock))
        visible = memory.visible(datetime(2018, 3, 1, 11, 15))
        self.assertEqual([record.symbol for record in visible], ["EARLY", "SAME"])

    def test_fewer_than_16_leaves_the_summary_empty(self):
        records = [_record(f"N{index}", datetime(2017, 1, index + 1), float(index)) for index in range(15)]
        memory = Memory(records)
        context = (0.0,)
        at = datetime(2018, 1, 1)
        self.assertEqual(memory.neighbors(context, at), ())
        self.assertIsNone(memory.summary(context, at))


class NearestNeighbors(unittest.TestCase):
    def test_rebuilding_reproduces_the_same_neighbors(self):
        records = [
            _record(f"N{index:02d}", datetime(2017, 1, 1, 11, 15), float(index), realized_r=-1.0 if index % 2 == 0 else None)
            for index in range(20)
        ]
        records.append(_record("FUTURE", datetime(2019, 1, 1, 11, 15), 0.0))
        context = (0.0,)
        at = datetime(2018, 6, 1, 11, 15)

        forward = Memory(records)
        backward = Memory(tuple(reversed(records)))
        self.assertEqual(forward.records, backward.records)
        self.assertEqual(forward.neighbors(context, at), backward.neighbors(context, at))

        symbols = [record.symbol for record in forward.neighbors(context, at)]
        self.assertEqual(symbols, [f"N{index:02d}" for index in range(NEIGHBOR_COUNT)])
        self.assertNotIn("FUTURE", symbols)

        summary = forward.summary(context, at)
        self.assertIsNotNone(summary)
        self.assertAlmostEqual(summary.complete_stop.share, 1.0)
        self.assertAlmostEqual(summary.complete_stop.average_r, -1.0)
        self.assertEqual(summary.uoc_touch.share, 0.0)
        self.assertIsNone(summary.uoc_touch.average_r)

    def test_the_average_r_uses_only_the_taken_trades_of_that_behavior(self):
        records = []
        for index in range(NEIGHBOR_COUNT):
            behavior = COMPLETE_STOP if index < 4 else UOC_TOUCH
            realized = -1.0 if index < 2 else None
            records.append(_record(f"N{index:02d}", datetime(2017, 1, 1), float(index), behavior, realized))
        summary = Memory(records).summary((0.0,), datetime(2018, 1, 1))
        self.assertAlmostEqual(summary.complete_stop.share, 4 / 16)
        self.assertAlmostEqual(summary.complete_stop.average_r, -1.0)
        self.assertAlmostEqual(summary.uoc_touch.share, 12 / 16)
        self.assertIsNone(summary.uoc_touch.average_r)


class RelianceMemory(unittest.TestCase):
    def test_a_2018_decision_sees_2016_and_cannot_see_2019(self):
        bars = load_bars(csv_path("RELIANCE"))
        picked = {}
        for item in accepted_zones(score_zones(bars)):
            decided = known_clock(bars[item.zone.end])
            if decided is None or decided.year not in (2016, 2018, 2019):
                continue
            if decided.year not in picked:
                picked[decided.year] = item
            if len(picked) == 3:
                break

        self.assertEqual(set(picked), {2016, 2018, 2019})
        records = []
        clocks = {}
        for year, item in picked.items():
            zone = item.zone
            signal = bars[zone.end]
            decided = known_clock(signal)
            resolved = resolution_clock(bars, zone.end)
            self.assertIsNotNone(decided)
            self.assertIsNotNone(resolved)
            self.assertGreater(resolved, decided)
            snapshot = snapshot_at(bars, zone, decided)
            plan = required_plan(bars, zone, item.probability)
            records.append(
                Record(
                    symbol=f"RELIANCE-{year}",
                    decided_at=decided,
                    resolved_at=resolved,
                    context=context_of(snapshot, plan, signal.close, signal.atr_14),
                    behavior=COMPLETE_STOP,
                    trade_result=None,
                    realized_r=None,
                )
            )
            clocks[year] = decided

        resolved_2016 = next(record.resolved_at for record in records if record.symbol.endswith("2016"))
        resolved_2019 = next(record.resolved_at for record in records if record.symbol.endswith("2019"))
        self.assertLessEqual(resolved_2016, clocks[2018])
        self.assertGreater(resolved_2019, clocks[2018])

        first = Memory(records)
        second = Memory(tuple(reversed(records)))
        self.assertEqual(first.records, second.records)
        visible = [record.symbol for record in first.visible(clocks[2018])]
        self.assertIn("RELIANCE-2016", visible)
        self.assertNotIn("RELIANCE-2018", visible)
        self.assertNotIn("RELIANCE-2019", visible)
        self.assertEqual(first.neighbors(records[-1].context, clocks[2018]), ())
        self.assertIsNone(first.summary(records[-1].context, clocks[2018]))


if __name__ == "__main__":
    unittest.main()
