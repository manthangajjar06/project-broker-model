import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.client import (
    MAX_CAPTION_LENGTH,
    TelegramError,
    TelegramSettings,
    _encode_multipart,
    send_document,
)


class EncodeMultipartTests(unittest.TestCase):
    def test_includes_fields_and_file_bytes(self):
        body = _encode_multipart(
            "BOUND",
            fields={"chat_id": "100"},
            files={"document": ("report.txt", b"hello", "text/plain")},
        )
        text = body.decode("utf-8", errors="replace")
        self.assertIn("chat_id", text)
        self.assertIn("100", text)
        self.assertIn('filename="report.txt"', text)
        self.assertIn("hello", text)
        self.assertTrue(body.endswith(b"--BOUND--\r\n"))


class SendDocumentTests(unittest.TestCase):
    def test_missing_file_is_refused(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        with patch("telegram.client.call_api_multipart") as call_api:
            with self.assertRaises(TelegramError):
                send_document(Path("does-not-exist.txt"), settings=settings)
        call_api.assert_not_called()

    def test_overlong_caption_is_refused(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zones.txt"
            path.write_text("zones\n", encoding="utf-8")
            with patch("telegram.client.call_api_multipart") as call_api:
                with self.assertRaises(TelegramError):
                    send_document(
                        path,
                        caption="x" * (MAX_CAPTION_LENGTH + 1),
                        settings=settings,
                    )
        call_api.assert_not_called()

    def test_uploads_saved_chat_document(self):
        settings = TelegramSettings(bot_token="secret-token", chat_id="100")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zones_nifty100.txt"
            path.write_bytes(b"report body\n")
            with patch(
                "telegram.client.call_api_multipart",
                return_value={"ok": True, "result": {"message_id": 9}},
            ) as call_api:
                result = send_document(path, caption="done", settings=settings)

        self.assertEqual(result["message_id"], 9)
        args, kwargs = call_api.call_args
        self.assertEqual(args[0], "secret-token")
        self.assertEqual(args[1], "sendDocument")
        self.assertEqual(kwargs["fields"]["chat_id"], "100")
        self.assertEqual(kwargs["fields"]["caption"], "done")
        filename, content, content_type = kwargs["files"]["document"]
        self.assertEqual(filename, "zones_nifty100.txt")
        self.assertEqual(content, b"report body\n")
        self.assertIn("text/plain", content_type)


if __name__ == "__main__":
    unittest.main()
