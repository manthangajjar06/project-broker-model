"""Small Telegram Bot API client.

Secrets are read from the project-root ``.env`` file or the process environment.
The bot token is never included in errors raised by this module. Outgoing
notifications go only to ``TELEGRAM_CHAT_ID`` unless a caller passes another id
on purpose (the setup script does that once, while discovering the chat).
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from telegram.env_file import ENV_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, load_env_file

API_ROOT = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024
# Telegram Bot API soft limit for sendDocument uploads from a bot.
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024


class TelegramError(RuntimeError):
    """Raised when configuration is missing or Telegram rejects a call."""


@dataclass(frozen=True)
class TelegramSettings:
    """Credentials for one local bot. ``chat_id`` is empty until setup binds it."""

    bot_token: str
    chat_id: str | None
    env_file: Path = ENV_FILE


@dataclass(frozen=True)
class ChatCandidate:
    """A person who messaged the bot, taken from a getUpdates payload."""

    chat_id: str
    label: str
    update_id: int


def load_settings(env_file: Path = ENV_FILE) -> TelegramSettings:
    """Load the bot token and optional trusted chat id.

    Process environment variables win over the env file. That lets tests and
    a future cron job inject values without rewriting the file.
    """

    file_values = load_env_file(env_file)
    token = _first_present(os.environ.get(TELEGRAM_BOT_TOKEN), file_values.get(TELEGRAM_BOT_TOKEN))
    chat_id = _first_present(os.environ.get(TELEGRAM_CHAT_ID), file_values.get(TELEGRAM_CHAT_ID))
    if not token:
        raise TelegramError(
            "TELEGRAM_BOT_TOKEN is missing. Add it to the project-root .env file "
            "or run: python telegram/setup.py"
        )
    return TelegramSettings(bot_token=token, chat_id=chat_id, env_file=env_file)


def is_allowed_chat(chat_id: str | int, settings: TelegramSettings) -> bool:
    """True only for the single chat saved during setup."""

    if not settings.chat_id:
        return False
    return str(chat_id) == str(settings.chat_id)


def send_message(
    text: str,
    *,
    chat_id: str | None = None,
    settings: TelegramSettings | None = None,
    parse_mode: str | None = None,
) -> dict:
    """Send one message. Uses the saved chat when ``chat_id`` is omitted.

    ``parse_mode`` may be ``HTML`` or ``MarkdownV2``. Leave it ``None`` for
    plain text (used by status / app-code prompts).
    """

    settings = settings or load_settings()
    destination = (chat_id or settings.chat_id or "").strip()
    if not destination:
        raise TelegramError(
            "TELEGRAM_CHAT_ID is missing. Run: python telegram/setup.py"
        )
    cleaned = text.strip()
    if not cleaned:
        raise TelegramError("Refusing to send an empty Telegram message.")
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise TelegramError(
            f"Telegram messages are limited to {MAX_MESSAGE_LENGTH} characters "
            f"(this one is {len(cleaned)})."
        )
    payload: dict[str, str] = {"chat_id": destination, "text": cleaned}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    response = call_api(
        settings.bot_token,
        "sendMessage",
        payload,
    )
    return response["result"]


def send_document(
    path: Path,
    *,
    caption: str | None = None,
    chat_id: str | None = None,
    settings: TelegramSettings | None = None,
) -> dict:
    """Upload one local file with Telegram ``sendDocument``.

    The trusted chat is used when ``chat_id`` is omitted. Captions are optional
    and must stay within Telegram's 1024-character limit.
    """

    settings = settings or load_settings()
    destination = (chat_id or settings.chat_id or "").strip()
    if not destination:
        raise TelegramError(
            "TELEGRAM_CHAT_ID is missing. Run: python telegram/setup.py"
        )

    file_path = Path(path)
    if not file_path.is_file():
        raise TelegramError(f"Cannot send Telegram document; file not found: {file_path}")

    size = file_path.stat().st_size
    if size <= 0:
        raise TelegramError(f"Cannot send an empty Telegram document: {file_path}")
    if size > MAX_DOCUMENT_BYTES:
        raise TelegramError(
            f"Telegram documents are limited to {MAX_DOCUMENT_BYTES} bytes "
            f"(this one is {size})."
        )

    cleaned_caption = None
    if caption is not None:
        cleaned_caption = caption.strip()
        if cleaned_caption and len(cleaned_caption) > MAX_CAPTION_LENGTH:
            raise TelegramError(
                f"Telegram captions are limited to {MAX_CAPTION_LENGTH} characters "
                f"(this one is {len(cleaned_caption)})."
            )

    fields = {"chat_id": destination}
    if cleaned_caption:
        fields["caption"] = cleaned_caption

    response = call_api_multipart(
        settings.bot_token,
        "sendDocument",
        fields=fields,
        files={
            "document": (
                file_path.name,
                file_path.read_bytes(),
                "text/plain; charset=utf-8",
            )
        },
        timeout_seconds=120,
    )
    return response["result"]


def get_updates(
    *,
    offset: int | None = None,
    timeout_seconds: int = 0,
    settings: TelegramSettings | None = None,
) -> list[dict]:
    """Return new bot updates. ``timeout_seconds`` is Telegram's long-poll wait."""

    settings = settings or load_settings()
    payload: dict[str, int] = {"timeout": max(0, timeout_seconds)}
    if offset is not None:
        payload["offset"] = offset
    response = call_api(
        settings.bot_token,
        "getUpdates",
        payload,
        timeout_seconds=timeout_seconds + 15,
    )
    result = response.get("result", [])
    if not isinstance(result, list):
        raise TelegramError("Telegram getUpdates returned an unexpected result.")
    return result


def get_me(settings: TelegramSettings | None = None) -> dict:
    """Return the bot profile Telegram associates with the saved token."""

    settings = settings or load_settings()
    response = call_api(settings.bot_token, "getMe", {})
    result = response.get("result")
    if not isinstance(result, dict):
        raise TelegramError("Telegram getMe returned an unexpected result.")
    return result


def call_api(token: str, method: str, payload: dict | None = None, timeout_seconds: int = 30) -> dict:
    """POST one Bot API method as JSON and return the decoded object."""

    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        api_url(token, method),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _execute_request(request, method=method, token=token, timeout_seconds=timeout_seconds)


def call_api_multipart(
    token: str,
    method: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    timeout_seconds: int = 60,
) -> dict:
    """POST one Bot API method as multipart form data (used for file uploads)."""

    boundary = f"----BrokerModelBoundary{uuid4().hex}"
    body = _encode_multipart(boundary, fields=fields, files=files)
    request = urllib.request.Request(
        api_url(token, method),
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    return _execute_request(request, method=method, token=token, timeout_seconds=timeout_seconds)


def _encode_multipart(
    boundary: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")

    for name, (filename, content, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(content)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks)


def _execute_request(
    request: urllib.request.Request,
    *,
    method: str,
    token: str,
    timeout_seconds: int,
) -> dict:
    """Run one HTTP call and turn Telegram failures into ``TelegramError``."""

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds, context=https_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise TelegramError(
            f"Telegram {method} failed ({error.code}): {_safe_detail(detail, token)}"
        ) from None
    except urllib.error.URLError as error:
        raise TelegramError(f"Could not reach Telegram: {error.reason}") from None
    except TimeoutError:
        raise TelegramError(f"Telegram {method} timed out after {timeout_seconds} seconds.") from None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise TelegramError("Telegram returned a response that was not JSON.") from error
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        description = _safe_detail(str(parsed), token)
        raise TelegramError(f"Telegram {method} was rejected: {description}")
    return parsed


def chat_candidates_from_updates(updates: list[dict]) -> list[ChatCandidate]:
    """Unique chats that sent a message, in the order they last appeared."""

    found: dict[str, ChatCandidate] = {}
    for update in updates:
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or {}
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        if not isinstance(chat, dict) or chat.get("id") is None:
            continue
        chat_id = str(chat["id"])
        found[chat_id] = ChatCandidate(
            chat_id=chat_id,
            label=describe_chat(chat),
            update_id=int(update.get("update_id") or 0),
        )
    return list(found.values())


def describe_chat(chat: dict) -> str:
    """Human-readable chat label. Never includes the bot token."""

    first_name = str(chat.get("first_name") or "").strip()
    last_name = str(chat.get("last_name") or "").strip()
    username = str(chat.get("username") or "").strip()
    name = " ".join(part for part in (first_name, last_name) if part)
    if username and name:
        return f"{name} (@{username})"
    if username:
        return f"@{username}"
    if name:
        return name
    return f"chat {chat.get('id')}"


def describe_bot(profile: dict) -> str:
    username = str(profile.get("username") or "").strip()
    if username:
        return f"@{username}"
    return str(profile.get("first_name") or "the bot")


def https_context() -> ssl.SSLContext:
    """Use the operating system's trusted certificates.

    Python's built-in CA list rejected Telegram on this PC (a self-signed
    certificate in the chain, which is common when security software scans
    HTTPS). The OS store already trusts that certificate, and verification
    stays enabled.
    """

    try:
        import truststore
    except ImportError as error:
        raise TelegramError(
            "The 'truststore' package is missing. Run: python -m pip install -r telegram/requirements.txt"
        ) from error
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def api_url(token: str, method: str) -> str:
    return f"{API_ROOT}/bot{token}/{method}"


def redact_secret(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "***")
    return text


def _safe_detail(detail: str, token: str) -> str:
    cleaned = redact_secret(detail, token).strip()
    if len(cleaned) > 500:
        return cleaned[:500] + "..."
    return cleaned or "no details"


def _first_present(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        stripped = value.strip().strip('"').strip("'")
        if stripped:
            return stripped
    return None
