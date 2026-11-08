"""Telegram bridge for the NIFTY 100 cron login.

Telegram owns delivery and waiting. This module only asks for an app code,
hands the digits to ``kite_login.submit_totp_code``, and reports the result.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

JOB_DIRECTORY = Path(__file__).resolve().parent
PROJECT_ROOT = JOB_DIRECTORY.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(JOB_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(JOB_DIRECTORY))

from kite_login import MAX_TOTP_TRIES, submit_totp_code  # noqa: E402
from telegram.app_code import DEFAULT_WAIT_SECONDS, wait_for_app_code  # noqa: E402
from telegram.client import TelegramError  # noqa: E402
from telegram import notify  # noqa: E402

LOG = logging.getLogger("kite_telegram")


async def enter_totp_via_telegram(page: Any, user_id: str) -> bool:
    """Ask Telegram for the app code and submit it to Kite. Up to 3 tries."""

    for attempt in range(1, MAX_TOTP_TRIES + 1):
        try:
            notify.notify_app_code_needed(
                user_id,
                attempt=attempt,
                max_attempts=MAX_TOTP_TRIES,
                wait_seconds=DEFAULT_WAIT_SECONDS,
            )
        except TelegramError as error:
            LOG.error("Could not ask Telegram for the app code: %s", error)
            return False

        code = await asyncio.to_thread(
            wait_for_app_code,
            timeout_seconds=DEFAULT_WAIT_SECONDS,
        )
        if code is None:
            try:
                notify.notify_app_code_timeout(
                    user_id,
                    attempt=attempt,
                    max_attempts=MAX_TOTP_TRIES,
                )
            except TelegramError:
                LOG.exception("Could not send the Telegram timeout notice.")
            continue

        try:
            notify.notify_app_code_received()
        except TelegramError:
            LOG.exception("Could not send the Telegram 'code received' notice.")

        accepted = await submit_totp_code(page, code)
        if accepted:
            try:
                notify.notify_app_code_accepted(user_id)
            except TelegramError:
                LOG.exception("Could not send the Telegram login-success notice.")
            return True

        LOG.warning("%s: Telegram app code was not accepted by Kite.", user_id)
        try:
            notify.notify_app_code_rejected(
                user_id,
                attempt=attempt,
                max_attempts=MAX_TOTP_TRIES,
            )
        except TelegramError:
            LOG.exception("Could not send the Telegram rejection notice.")

    return False
