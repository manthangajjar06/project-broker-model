import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.env_file import load_env_file, parse_env_text, upsert_env_values


class EnvFileTests(unittest.TestCase):
    def test_parse_ignores_comments_and_unquotes_values(self):
        values = parse_env_text(
            "\n".join(
                [
                    "# comment",
                    "",
                    "TELEGRAM_BOT_TOKEN=123:abc",
                    'TELEGRAM_CHAT_ID="42"',
                    "NOTE=hello world",
                ]
            )
        )
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "123:abc")
        self.assertEqual(values["TELEGRAM_CHAT_ID"], "42")
        self.assertEqual(values["NOTE"], "hello world")

    def test_upsert_updates_one_key_and_keeps_the_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("# keep me\nOTHER=1\nTELEGRAM_CHAT_ID=old\n", encoding="utf-8")
            upsert_env_values(path, {"TELEGRAM_CHAT_ID": "99", "TELEGRAM_BOT_TOKEN": "123:abc"})
            text = path.read_text(encoding="utf-8")
            values = load_env_file(path)

        self.assertIn("# keep me", text)
        self.assertEqual(values["OTHER"], "1")
        self.assertEqual(values["TELEGRAM_CHAT_ID"], "99")
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "123:abc")

    def test_missing_file_is_empty(self):
        self.assertEqual(load_env_file(Path("this-file-does-not-exist.env")), {})


if __name__ == "__main__":
    unittest.main()
