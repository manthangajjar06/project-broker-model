"""Bind this PC to one Telegram chat and send a test message.

Run from the project root:

    python telegram/setup.py

The bot token and chat id are written to the project-root ``.env`` file.
Nothing in this script prints the token.
"""

from __future__ import annotations

import getpass
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from telegram.client import (  # noqa: E402
    ChatCandidate,
    TelegramError,
    chat_candidates_from_updates,
    describe_bot,
    get_me,
    get_updates,
    load_settings,
    send_message,
)
from telegram.env_file import ENV_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, load_env_file, upsert_env_values  # noqa: E402

WAIT_SECONDS = 90
POLL_SECONDS = 20
CONNECTED_TEXT = "Project Broker Model: Telegram connected."


def main() -> int:
    print("Telegram setup")
    print(f"Secrets file: {ENV_FILE}")
    print()

    try:
        token = ensure_token()
        settings = load_settings()
        profile = get_me(settings)
    except TelegramError as error:
        print(f"Setup stopped: {error}")
        return 1

    bot_name = describe_bot(profile)
    print(f"Token accepted. This process will listen as {bot_name}.")
    print()
    print(f"On your phone, open Telegram and send /start to {bot_name}.")
    print(f"Waiting up to {WAIT_SECONDS} seconds for that message...")

    try:
        chosen = wait_for_chat(settings)
    except TelegramError as error:
        print(f"Setup stopped: {error}")
        return 1

    if chosen is None:
        print()
        print(f"No message arrived. Open {bot_name}, send /start, and run this script again.")
        return 1

    upsert_env_values(
        ENV_FILE,
        {
            TELEGRAM_BOT_TOKEN: token,
            TELEGRAM_CHAT_ID: chosen.chat_id,
        },
    )
    print()
    print(f"Saved chat {chosen.chat_id} ({chosen.label}).")

    try:
        send_message(CONNECTED_TEXT, chat_id=chosen.chat_id, settings=load_settings())
    except TelegramError as error:
        print(f"The chat id was saved, but the test message failed: {error}")
        return 1

    print(f"Sent a test message to {chosen.label}. Check Telegram for:")
    print(f"    {CONNECTED_TEXT}")
    return 0


def ensure_token() -> str:
    """Return a token from .env, or ask once and store it."""

    existing = load_env_file().get(TELEGRAM_BOT_TOKEN, "").strip()
    if existing:
        print("Using TELEGRAM_BOT_TOKEN already stored in .env.")
        return existing

    print("No bot token is stored yet.")
    entered = getpass.getpass("Paste the bot token from BotFather (input is hidden): ").strip()
    if not entered:
        raise TelegramError("A bot token is required.")
    upsert_env_values(ENV_FILE, {TELEGRAM_BOT_TOKEN: entered})
    print("Stored the token in .env. It was not printed.")
    return entered


def wait_for_chat(settings) -> ChatCandidate | None:
    """Long-poll until one private chat messages the bot, or the wait expires."""

    deadline = time.monotonic() + WAIT_SECONDS
    offset: int | None = None
    collected: list[dict] = []

    while time.monotonic() < deadline:
        remaining = int(deadline - time.monotonic())
        timeout_seconds = min(POLL_SECONDS, max(1, remaining))
        updates = get_updates(offset=offset, timeout_seconds=timeout_seconds, settings=settings)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            collected.append(update)

        candidates = chat_candidates_from_updates(collected)
        if not candidates:
            continue
        if len(candidates) == 1:
            return candidates[0]
        return choose_candidate(candidates)

    return None


def choose_candidate(candidates: list[ChatCandidate]) -> ChatCandidate | None:
    print()
    print("More than one chat messaged the bot. Pick the phone that should receive alerts:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"  {index}. {candidate.label} (chat {candidate.chat_id})")

    raw = input("Enter the number to trust (blank to cancel): ").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise TelegramError("Enter the number shown next to the chat, or leave the line blank to cancel.")
    choice = int(raw)
    if choice < 1 or choice > len(candidates):
        raise TelegramError("That number is not in the list.")
    return candidates[choice - 1]


if __name__ == "__main__":
    raise SystemExit(main())
