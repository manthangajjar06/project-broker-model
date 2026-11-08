"""Nightly entry point for Windows Task Scheduler (9:00 PM).

Run from the project root:

    python telegram/nightly.py

Uses the same lock as the Telegram bot. If a scan is already running, this
script notifies Telegram and exits without starting a second one.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram.client import TelegramError, send_message  # noqa: E402
from telegram.scan_control import try_start_scan  # noqa: E402

LOG = logging.getLogger("telegram.nightly")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = try_start_scan(trigger="nightly")
    try:
        if result.started:
            send_message(
                "Nightly 9:00 PM scan started on this PC.\n"
                f"{result.message}"
            )
        else:
            send_message(
                "Nightly 9:00 PM trigger fired, but no new scan was started.\n"
                f"{result.message}"
            )
    except TelegramError as error:
        LOG.error("Could not send the nightly Telegram notice: %s", error)
        # Still succeed if the scan itself started; Telegram notice is best-effort.
        if not result.started:
            return 1

    return 0 if result.started or "already running" in result.message.lower() else 1


if __name__ == "__main__":
    raise SystemExit(main())
