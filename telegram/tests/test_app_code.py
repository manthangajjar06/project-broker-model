import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.app_code import parse_app_code, wait_for_app_code
from telegram.client import TelegramSettings


class ParseAppCodeTests(unittest.TestCase):
    def test_accepts_plain_six_digits(self):
        self.assertEqual(parse_app_code("018659"), "018659")

    def test_accepts_spaced_or_hyphenated_digits(self):
        self.assertEqual(parse_app_code("018 659"), "018659")
        self.assertEqual(parse_app_code("018-659"), "018659")

    def test_rejects_sentences_and_wrong_lengths(self):
        self.assertIsNone(parse_app_code("code is 018659"))
        self.assertIsNone(parse_app_code("01865"))
        self.assertIsNone(parse_app_code("0186590"))
        self.assertIsNone(parse_app_code(""))
        self.assertIsNone(parse_app_code(None))


class WaitForAppCodeTests(unittest.TestCase):
    def test_returns_code_from_trusted_chat_only(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        updates = [
            {
                "update_id": 1,
                "message": {"chat": {"id": 999}, "text": "111111"},
            },
            {
                "update_id": 2,
                "message": {"chat": {"id": 100}, "text": "hello"},
            },
            {
                "update_id": 3,
                "message": {"chat": {"id": 100}, "text": "222222"},
            },
        ]
        with (
            patch("telegram.app_code.discard_pending_updates", return_value=None),
            patch("telegram.app_code.get_updates", return_value=updates),
            patch("telegram.app_code.send_message") as send_message,
            patch("telegram.app_code.time.monotonic", return_value=100.0),
        ):
            code = wait_for_app_code(timeout_seconds=30, settings=settings)

        self.assertEqual(code, "222222")
        send_message.assert_called_once()
        self.assertIn("6-digit", send_message.call_args.args[0])

    def test_timeout_returns_none(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        # deadline is set from the first reading; the third reading ends the wait.
        ticks = [0.0, 0.0, 0.5, 2.0]

        def next_tick():
            return ticks.pop(0) if ticks else 99.0

        with (
            patch("telegram.app_code.discard_pending_updates", return_value=None),
            patch("telegram.app_code.get_updates", return_value=[]),
            patch("telegram.app_code.time.monotonic", side_effect=next_tick),
        ):
            code = wait_for_app_code(timeout_seconds=1, settings=settings)
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
