import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.client import (
    MAX_MESSAGE_LENGTH,
    TelegramError,
    TelegramSettings,
    chat_candidates_from_updates,
    describe_bot,
    describe_chat,
    is_allowed_chat,
    load_settings,
    redact_secret,
    send_message,
)
from telegram.env_file import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


class SettingsTests(unittest.TestCase):
    def test_environment_overrides_the_file(self):
        with patch("telegram.client.load_env_file", return_value={TELEGRAM_BOT_TOKEN: "file-token", TELEGRAM_CHAT_ID: "1"}):
            with patch.dict("os.environ", {TELEGRAM_BOT_TOKEN: "env-token", TELEGRAM_CHAT_ID: "2"}, clear=False):
                settings = load_settings()
        self.assertEqual(settings.bot_token, "env-token")
        self.assertEqual(settings.chat_id, "2")

    def test_missing_token_names_the_setup_command(self):
        with patch("telegram.client.load_env_file", return_value={}):
            with patch.dict("os.environ", {TELEGRAM_BOT_TOKEN: "", TELEGRAM_CHAT_ID: ""}, clear=False):
                with self.assertRaises(TelegramError) as caught:
                    load_settings()
        self.assertIn("python telegram/setup.py", str(caught.exception))
        self.assertNotIn("file-token", str(caught.exception))


class AllowlistTests(unittest.TestCase):
    def test_only_the_saved_chat_is_allowed(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        self.assertTrue(is_allowed_chat(100, settings))
        self.assertTrue(is_allowed_chat("100", settings))
        self.assertFalse(is_allowed_chat("101", settings))

    def test_unset_chat_allows_nobody(self):
        settings = TelegramSettings(bot_token="secret", chat_id=None)
        self.assertFalse(is_allowed_chat("100", settings))


class UpdateParsingTests(unittest.TestCase):
    def test_latest_message_wins_for_the_same_chat(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 7, "first_name": "Ada", "username": "ada"}}},
            {"update_id": 2, "message": {"chat": {"id": 7, "first_name": "Ada", "username": "ada"}}},
            {"update_id": 3, "edited_message": {"chat": {"id": 8, "username": "other"}}},
            {"update_id": 4},
        ]
        candidates = chat_candidates_from_updates(updates)
        self.assertEqual([item.chat_id for item in candidates], ["7", "8"])
        self.assertEqual(candidates[0].label, "Ada (@ada)")
        self.assertEqual(candidates[0].update_id, 2)
        self.assertEqual(describe_chat({"id": 9}), "chat 9")
        self.assertEqual(describe_bot({"username": "zerai6Bot"}), "@zerai6Bot")


class SendMessageTests(unittest.TestCase):
    def test_empty_text_is_refused_before_any_network_call(self):
        settings = TelegramSettings(bot_token="secret-token", chat_id="100")
        with patch("telegram.client.call_api") as call_api:
            with self.assertRaises(TelegramError):
                send_message("   ", settings=settings)
        call_api.assert_not_called()

    def test_missing_chat_is_refused_before_any_network_call(self):
        settings = TelegramSettings(bot_token="secret-token", chat_id=None)
        with patch("telegram.client.call_api") as call_api:
            with self.assertRaises(TelegramError) as caught:
                send_message("hello", settings=settings)
        call_api.assert_not_called()
        self.assertNotIn("secret-token", str(caught.exception))

    def test_overlong_text_is_refused(self):
        settings = TelegramSettings(bot_token="secret-token", chat_id="100")
        with self.assertRaises(TelegramError):
            send_message("x" * (MAX_MESSAGE_LENGTH + 1), settings=settings)

    def test_send_uses_the_saved_chat(self):
        settings = TelegramSettings(bot_token="secret-token", chat_id="100")
        with patch("telegram.client.call_api", return_value={"ok": True, "result": {"message_id": 5}}) as call_api:
            result = send_message("  hello  ", settings=settings)
        call_api.assert_called_once_with(
            "secret-token",
            "sendMessage",
            {"chat_id": "100", "text": "hello"},
        )
        self.assertEqual(result["message_id"], 5)


class RedactionTests(unittest.TestCase):
    def test_token_is_removed_from_error_text(self):
        self.assertEqual(redact_secret("bad token secret-token here", "secret-token"), "bad token *** here")


if __name__ == "__main__":
    unittest.main()
