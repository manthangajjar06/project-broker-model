"""Human-readable Telegram messages used by the NIFTY 100 cron job.

These helpers only format and send messages or files. Waiting for an app code
lives in ``telegram.app_code``. Login and chart scanning stay in ``crone-job``.
"""

from __future__ import annotations

import logging

from telegram.client import (
    MAX_MESSAGE_LENGTH,
    TelegramError,
    TelegramSettings,
    load_settings,
    send_message,
)

LOG = logging.getLogger("telegram.notify")


def notify_scan_started(*, limit: int | None = None, settings: TelegramSettings | None = None) -> None:
    """Tell the operator that the cron job has begun."""

    if limit is None:
        scope = "full NIFTY 100 list"
    else:
        scope = f"first {limit} symbol(s) only (--limit {limit})"

    text = (
        "NIFTY 100 fresh-zone scan started.\n"
        f"Scope: {scope}.\n"
        "\n"
        "I will ask here for the Zerodha 6-digit app code if Kite needs it "
        "before the charts can be scanned."
    )
    _send(text, settings=settings)


def notify_already_logged_in(settings: TelegramSettings | None = None) -> None:
    text = (
        "Kite is already logged in in Brave.\n"
        "No app code is needed. The scan will continue."
    )
    _send(text, settings=settings)


def notify_app_code_needed(
    user_id: str,
    *,
    attempt: int,
    max_attempts: int,
    wait_seconds: int,
    settings: TelegramSettings | None = None,
) -> None:
    text = (
        f"Kite needs the 6-digit app code for account {user_id}.\n"
        f"Attempt {attempt} of {max_attempts}.\n"
        "\n"
        "Open your authenticator app and reply here with only the six digits.\n"
        f"I will wait up to {wait_seconds} seconds for this attempt."
    )
    _send(text, settings=settings)


def notify_app_code_received(settings: TelegramSettings | None = None) -> None:
    _send("App code received. Submitting it to Kite now.", settings=settings)


def notify_app_code_accepted(user_id: str, settings: TelegramSettings | None = None) -> None:
    _send(
        f"Login succeeded for {user_id}.\nThe scan will continue.",
        settings=settings,
    )


def notify_app_code_rejected(
    user_id: str,
    *,
    attempt: int,
    max_attempts: int,
    settings: TelegramSettings | None = None,
) -> None:
    if attempt >= max_attempts:
        text = (
            f"Kite did not accept the app code for {user_id}.\n"
            "No attempts left for this account. Moving on if another saved account exists."
        )
    else:
        text = (
            f"Kite did not accept the app code for {user_id}.\n"
            "App codes expire every 30 seconds. I will ask again."
        )
    _send(text, settings=settings)


def notify_app_code_timeout(
    user_id: str,
    *,
    attempt: int,
    max_attempts: int,
    settings: TelegramSettings | None = None,
) -> None:
    text = (
        f"Timed out waiting for the app code for {user_id} "
        f"(attempt {attempt} of {max_attempts})."
    )
    _send(text, settings=settings)


def notify_login_failed(settings: TelegramSettings | None = None) -> None:
    _send(
        "Could not complete Kite login.\n"
        "The scan stopped. Fix the account or app code, then run the cron job again.",
        settings=settings,
    )


def notify_scan_completed(
    *,
    scanned_ok: int,
    failed: int,
    unresolved: int,
    fresh_zone_count: int,
    detail_blocks: list[str] | None = None,
    settings: TelegramSettings | None = None,
) -> None:
    """Send a completion summary, then formatted zone detail messages.

    Each detail block is already HTML (one symbol, or failures). Blocks are
    packed into as few messages as possible without cutting a block in half
    when it fits. The local ``zones_nifty100.txt`` file is unchanged.
    """

    settings = settings or load_settings()
    summary = _scan_completed_summary(
        scanned_ok=scanned_ok,
        failed=failed,
        unresolved=unresolved,
        fresh_zone_count=fresh_zone_count,
    )
    _send(summary, settings=settings)

    chunks = pack_html_blocks(detail_blocks or [])
    if not chunks:
        return

    total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        if total == 1:
            header = "<b>Fresh zones</b>"
        else:
            header = f"<b>Fresh zones</b> (part {index}/{total})"
        _send(f"{header}\n\n{chunk}", settings=settings, parse_mode="HTML")


def pack_html_blocks(blocks: list[str], *, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Join whole HTML blocks into Telegram-sized messages.

    A block that is somehow larger than the limit is sent alone after a safe
    plain-text trim, so one oversized symbol cannot drop the rest of the report.
    """

    # Leave room for the "Fresh zones (part x/y)" header above each chunk.
    usable = max_length - 80
    if usable < 1:
        usable = max_length

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for block in blocks:
        cleaned = block.strip()
        if not cleaned:
            continue
        if len(cleaned) > usable:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_length = 0
            chunks.append(_fit_single_line(cleaned, usable))
            continue

        # +2 accounts for the blank line between packed blocks.
        added = len(cleaned) + (2 if current else 0)
        if current and current_length + added > usable:
            chunks.append("\n\n".join(current))
            current = [cleaned]
            current_length = len(cleaned)
            continue
        current.append(cleaned)
        current_length += added

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _fit_single_line(line: str, max_length: int) -> str:
    if len(line) <= max_length:
        return line
    keep = max(0, max_length - 3)
    return line[:keep] + "..."


def _scan_completed_summary(
    *,
    scanned_ok: int,
    failed: int,
    unresolved: int,
    fresh_zone_count: int,
) -> str:
    lines = [
        "NIFTY 100 fresh-zone scan finished.",
        (
            f"Scanned OK: {scanned_ok} | Failed: {failed} | "
            f"No Kite token: {unresolved}"
        ),
        f"Fresh zones found: {fresh_zone_count}",
    ]
    if fresh_zone_count == 0:
        lines.append("")
        lines.append("No fresh zones were found in this run.")
    else:
        lines.append("")
        lines.append("Zone details follow in the next message(s).")
    return "\n".join(lines)


def _send(
    text: str,
    *,
    settings: TelegramSettings | None,
    parse_mode: str | None = None,
) -> None:
    settings = settings or load_settings()
    try:
        send_message(text, settings=settings, parse_mode=parse_mode)
    except TelegramError:
        LOG.exception("Failed to send Telegram notification.")
        raise
