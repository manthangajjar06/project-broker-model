"""Wait for a Zerodha 6-digit app code from the trusted Telegram chat.

Pending messages are discarded before each wait so an older chat message
cannot be reused as the current login code. The digits themselves are never
written to disk and never echoed back in bot replies.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from telegram.app_code_bridge import clear_app_code, consume_app_code
from telegram.client import TelegramError, TelegramSettings, get_updates, is_allowed_chat, load_settings, send_message

LOG = logging.getLogger("telegram.app_code")

# Long enough to open the authenticator app; still short enough that a hung
# cron job does not wait forever for one attempt.
DEFAULT_WAIT_SECONDS = 180
# Short polls so a code dropped by the command bot is noticed quickly.
POLL_SECONDS = 5

# Whole message is six digits, optionally with spaces or hyphens between them.
_CODE_ONLY = re.compile(r"^\s*(\d[\s\-]*){6}\s*$")
_DIGITS = re.compile(r"\d")


@dataclass(frozen=True)
class IncomingText:
    """One text message from Telegram, already filtered for our trusted chat."""

    update_id: int
    text: str


def parse_app_code(text: str) -> str | None:
    """Return the six digits when ``text`` is clearly only an app code.

    Anything else returns ``None`` so a normal chat sentence is never treated
    as a TOTP value.
    """

    if text is None:
        return None
    if not _CODE_ONLY.match(text):
        return None
    digits = "".join(_DIGITS.findall(text))
    if len(digits) != 6:
        return None
    return digits


def discard_pending_updates(settings: TelegramSettings | None = None) -> int | None:
    """Drop every update currently waiting for this bot.

    Returns the next offset Telegram should use, or ``None`` when the queue
    was already empty.
    """

    settings = settings or load_settings()
    updates = get_updates(timeout_seconds=0, settings=settings)
    if not updates:
        return None

    highest = max(int(update.get("update_id") or 0) for update in updates)
    # Asking again with offset = last_id + 1 confirms those updates as seen.
    get_updates(offset=highest + 1, timeout_seconds=0, settings=settings)
    LOG.info("Discarded %d pending Telegram update(s).", len(updates))
    return highest + 1


def wait_for_app_code(
    *,
    timeout_seconds: int = DEFAULT_WAIT_SECONDS,
    settings: TelegramSettings | None = None,
    start_offset: int | None = None,
) -> str | None:
    """Block until the trusted chat sends a valid app code, or time runs out.

    Invalid replies get a short reminder. Messages from any other chat are
    ignored. Returns ``None`` on timeout.
    """

    settings = settings or load_settings()
    if not settings.chat_id:
        raise TelegramError(
            "TELEGRAM_CHAT_ID is missing. Run: python telegram/setup.py"
        )

    offset = start_offset
    if offset is None:
        offset = discard_pending_updates(settings)
    clear_app_code()

    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        bridged = consume_app_code()
        if bridged is not None:
            LOG.info("Received a 6-digit app code via the local bot bridge.")
            return bridged

        remaining = int(deadline - time.monotonic())
        poll_timeout = min(POLL_SECONDS, max(1, remaining))
        try:
            updates = get_updates(offset=offset, timeout_seconds=poll_timeout, settings=settings)
        except TelegramError as error:
            # Another local process (the command bot) may still be long-polling.
            # Keep waiting; the bot bridge can still deliver the digits.
            LOG.warning("getUpdates while waiting for app code: %s", error)
            time.sleep(2)
            continue

        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1

            incoming = _trusted_text_message(update, settings)
            if incoming is None:
                continue

            code = parse_app_code(incoming.text)
            if code is not None:
                LOG.info("Received a 6-digit app code from the trusted Telegram chat.")
                return code

            send_message(
                "That did not look like a 6-digit app code.\n"
                "Reply with only the six digits from your authenticator app.",
                settings=settings,
            )

    LOG.warning("Timed out after %d seconds waiting for an app code.", timeout_seconds)
    return None


def _trusted_text_message(update: dict, settings: TelegramSettings) -> IncomingText | None:
    if not isinstance(update, dict):
        return None
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    if not isinstance(chat, dict) or chat.get("id") is None:
        return None
    if not is_allowed_chat(chat["id"], settings):
        LOG.warning("Ignoring Telegram message from unexpected chat %s.", chat.get("id"))
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    update_id = update.get("update_id")
    return IncomingText(update_id=int(update_id or 0), text=text)
