import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram.client import TelegramSettings
from telegram.notify import (
    _scan_completed_summary,
    notify_scan_completed,
    pack_html_blocks,
)


class ScanCompletedSummaryTests(unittest.TestCase):
    def test_includes_counts(self):
        text = _scan_completed_summary(
            scanned_ok=2,
            failed=1,
            unresolved=0,
            fresh_zone_count=3,
        )
        self.assertIn("scan finished", text)
        self.assertIn("Fresh zones found: 3", text)
        self.assertIn("Zone details follow", text)

    def test_mentions_empty_result(self):
        text = _scan_completed_summary(
            scanned_ok=1,
            failed=0,
            unresolved=0,
            fresh_zone_count=0,
        )
        self.assertIn("No fresh zones were found", text)


class PackHtmlBlocksTests(unittest.TestCase):
    def test_keeps_small_blocks_together(self):
        chunks = pack_html_blocks(["AAA", "BBB"], max_length=200)
        self.assertEqual(chunks, ["AAA\n\nBBB"])

    def test_splits_when_blocks_do_not_fit(self):
        chunks = pack_html_blocks(["AAAA", "BBBB", "CCCC"], max_length=90)
        self.assertGreaterEqual(len(chunks), 2)
        joined = "\n".join(chunks)
        self.assertIn("AAAA", joined)
        self.assertIn("CCCC", joined)


class NotifyScanCompletedTests(unittest.TestCase):
    def test_sends_summary_then_html_zone_messages(self):
        settings = TelegramSettings(bot_token="secret", chat_id="100")
        block = (
            "<b>NSE:ABB</b> — 2 fresh zone(s)\n\n"
            "<b>#1 RBR · SINGLE</b>\n"
            "Formed: 02 Feb 2026, 15:15\n"
            "Zone: <code>5454.50 – 5483.00</code>\n"
            "Entry: <code>5483.00</code>\n"
            "ML: <b>REJECTED</b> (32.85%)"
        )
        with patch("telegram.notify.send_message") as send_message:
            notify_scan_completed(
                scanned_ok=1,
                failed=0,
                unresolved=0,
                fresh_zone_count=2,
                detail_blocks=[block],
                settings=settings,
            )

        self.assertEqual(send_message.call_count, 2)
        summary_call = send_message.call_args_list[0]
        detail_call = send_message.call_args_list[1]
        self.assertIn("scan finished", summary_call.args[0])
        self.assertIsNone(summary_call.kwargs.get("parse_mode"))
        self.assertIn("<b>Fresh zones</b>", detail_call.args[0])
        self.assertIn("NSE:ABB", detail_call.args[0])
        self.assertEqual(detail_call.kwargs.get("parse_mode"), "HTML")


if __name__ == "__main__":
    unittest.main()
