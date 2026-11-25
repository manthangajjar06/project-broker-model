"""A both-touched candle stops and asks. The answer is stored."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Model.both_touched import (  # noqa: E402
    BatchBothTouched,
    answer_key,
    load_answers,
    resolve_both,
    save_answers,
)
from Model.fill import STOP, TARGET, BothTouched  # noqa: E402


class BothTouchedAnswers(unittest.TestCase):
    def test_the_cmd_answer_is_saved_and_reused(self):
        hit = BothTouched("RELIANCE", "2020-01-15", "11:15:00", 100.0, 95.0, 110.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "answers.json"
            calls = []

            def ask(prompt):
                calls.append(prompt)
                return "target"

            first = resolve_both(hit, answers={}, path=path, ask=ask)
            self.assertEqual(first, TARGET)
            self.assertEqual(len(calls), 1)
            stored = load_answers(path)
            self.assertEqual(stored[answer_key(hit)], TARGET)

            second = resolve_both(hit, path=path, ask=ask)
            self.assertEqual(second, TARGET)
            self.assertEqual(len(calls), 1)

    def test_stop_aliases_are_accepted(self):
        hit = BothTouched("TCS", "2021-06-01", "13:15:00", 50.0, 48.0, 54.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "answers.json"
            choice = resolve_both(hit, answers={}, path=path, ask=lambda _prompt: "SL")
            self.assertEqual(choice, STOP)

    def test_batch_uses_hand_answer_else_stop_first(self):
        hit = BothTouched("RELIANCE", "2020-01-15", "11:15:00", 100.0, 95.0, 110.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "answers.json"
            save_answers({answer_key(hit): TARGET}, path)
            batch = BatchBothTouched(path)
            self.assertEqual(batch(hit), TARGET)
            self.assertEqual(batch.stop_first, [])

            other = BothTouched("TCS", "2021-06-01", "13:15:00", 50.0, 48.0, 54.0)
            self.assertEqual(batch(other), STOP)
            self.assertEqual(batch.stop_first, [answer_key(other)])
            self.assertNotIn(answer_key(other), load_answers(path))


if __name__ == "__main__":
    unittest.main()
