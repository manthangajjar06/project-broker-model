"""Always-on Telegram command listener for this PC.

Run from the project root (leave this window open, or auto-start it with Windows):

    python telegram/bot.py

Commands (trusted chat only):
  /scan       start a full NIFTY 100 scan
  /scan 3     start a short test scan (first 3 symbols)
  /status     show whether a scan is running
  /help       list commands

While a scan is running this listener stops calling getUpdates so the scanner
can receive the Zerodha app code on Telegram without competing for updates.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram.app_code import parse_app_code  # noqa: E402
from telegram.app_code_bridge import publish_app_code  # noqa: E402
from telegram.client import (  # noqa: E402
    TelegramError,
    get_updates,
    is_allowed_chat,
    load_settings,
    send_message,
)
from telegram.scan_control import (  # noqa: E402
    format_status,
    get_status,
    try_start_scan,
    wait_until_scan_finishes,
)

LOG = logging.getLogger("telegram.bot")
POLL_SECONDS = 25
COMMAND_RE = re.compile(r"^/([a-zA-Z0-9_]+)(?:@\w+)?(?:\s+(.*))?$")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        settings = load_settings()
    except TelegramError as error:
        print(f"Bot cannot start: {error}")
        return 1
    if not settings.chat_id:
        print("TELEGRAM_CHAT_ID is missing. Run: python telegram/setup.py")
        return 1

    print("Telegram command bot is running.")
    print("Trusted chat only. Commands: /scan, /status, /help")
    print("Press Ctrl+C to stop.")
    try:
        send_message(
            "Project Broker Model bot is online on this PC.\n"
            "Commands: /scan, /scan 3, /status, /help",
            settings=settings,
        )
    except TelegramError as error:
        LOG.error("Could not send the online notice: %s", error)

    offset: int | None = None
    try:
        while True:
            # If a scan was started outside this bot (Task Scheduler), wait
            # without consuming Telegram updates until it finishes.
            if get_status().running:
                LOG.info("Scan already running - pausing command polling.")
                wait_until_scan_finishes()
                LOG.info("Scan finished - resuming command polling.")
                continue

            try:
                updates = get_updates(
                    offset=offset,
                    timeout_seconds=POLL_SECONDS,
                    settings=settings,
                )
            except TelegramError as error:
                LOG.error("getUpdates failed: %s", error)
                time.sleep(5)
                continue

            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                # Nightly may have started during this long-poll. Forward app
                # codes to the scanner instead of treating them as commands.
                if get_status().running:
                    _forward_app_code_if_present(update, settings)
                else:
                    _handle_update(update, settings)
    except KeyboardInterrupt:
        print("\nBot stopped.")
        return 0


def _forward_app_code_if_present(update: dict, settings) -> None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    if not isinstance(chat, dict) or not is_allowed_chat(chat.get("id"), settings):
        return
    text = message.get("text")
    if not isinstance(text, str):
        return
    code = parse_app_code(text)
    if code is None:
        return
    publish_app_code(code)
    try:
        send_message("App code received and passed to the scanner.", settings=settings)
    except TelegramError:
        LOG.exception("Could not acknowledge the bridged app code.")


def _handle_update(update: dict, settings) -> None:
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    if not isinstance(chat, dict) or chat.get("id") is None:
        return
    if not is_allowed_chat(chat["id"], settings):
        LOG.warning("Ignoring command from unexpected chat %s", chat.get("id"))
        return

    text = message.get("text")
    if not isinstance(text, str):
        return
    match = COMMAND_RE.match(text.strip())
    if not match:
        return

    command = match.group(1).lower()
    argument = (match.group(2) or "").strip()
    try:
        if command in {"help", "start"}:
            send_message(_help_text(), settings=settings)
            return
        if command == "status":
            send_message(format_status(), settings=settings)
            return
        if command == "scan":
            _handle_scan(argument, settings)
            return
        send_message(
            f"Unknown command /{command}.\nSend /help for the list.",
            settings=settings,
        )
    except TelegramError:
        LOG.exception("Failed while handling /%s", command)


def _handle_scan(argument: str, settings) -> None:
    limit = None
    if argument:
        if not argument.isdigit():
            send_message(
                "Usage:\n/scan\n/scan 3\n(the number is an optional --limit)",
                settings=settings,
            )
            return
        limit = int(argument)

    result = try_start_scan(trigger="telegram", limit=limit)
    send_message(result.message, settings=settings)
    if not result.started:
        return

    # Release getUpdates to the scanner for app-code collection.
    wait_until_scan_finishes()
    send_message(
        "Scan process finished.\n"
        "If zones were found they were already sent above.\n"
        "Command listening is active again.",
        settings=settings,
    )


def _help_text() -> str:
    return (
        "Project Broker Model commands:\n"
        "\n"
        "/scan — start a full NIFTY 100 fresh-zone scan\n"
        "/scan 3 — test run on the first 3 symbols\n"
        "/status — show whether a scan is running\n"
        "/help — show this list\n"
        "\n"
        "Nightly 9:00 PM runs use the same scanner on this PC."
    )


if __name__ == "__main__":
    raise SystemExit(main())
