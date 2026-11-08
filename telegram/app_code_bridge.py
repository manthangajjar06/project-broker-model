"""Hand a Telegram app code from the command bot to the scanner.

Only one process should call Telegram ``getUpdates`` at a time. While the bot
is still finishing a long-poll, a nightly scan may already be waiting for TOTP.
In that overlap the bot writes the six digits here and the scanner reads them.
"""

from __future__ import annotations

from pathlib import Path

PENDING_APP_CODE_FILE = Path(__file__).resolve().parent / ".pending_app_code"


def publish_app_code(code: str) -> None:
    cleaned = "".join(character for character in code if character.isdigit())
    PENDING_APP_CODE_FILE.write_text(cleaned, encoding="utf-8")


def consume_app_code() -> str | None:
    if not PENDING_APP_CODE_FILE.is_file():
        return None
    try:
        raw = PENDING_APP_CODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        PENDING_APP_CODE_FILE.unlink()
    except OSError:
        pass
    digits = "".join(character for character in raw if character.isdigit())
    if len(digits) != 6:
        return None
    return digits


def clear_app_code() -> None:
    try:
        PENDING_APP_CODE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
