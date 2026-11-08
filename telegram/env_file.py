"""Read and update the project-root ``.env`` file.

The file is a list of ``KEY=VALUE`` lines. Blank lines and ``#`` comments are
kept when a value is updated, so unrelated settings are not rewritten.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"


def parse_env_text(text: str) -> dict[str, str]:
    """Return the keys and values stored in an env file."""

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        key, value = _parse_assignment(raw_line)
        if key is not None:
            values[key] = value or ""
    return values


def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Load ``path``. A missing file is an empty configuration, not an error."""

    if not path.is_file():
        return {}
    return parse_env_text(path.read_text(encoding="utf-8-sig"))


def upsert_env_values(path: Path, updates: dict[str, str]) -> None:
    """Set each key in ``updates``, preserving every other line in the file."""

    existing_lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    remaining = dict(updates)
    rewritten: list[str] = []

    for line in existing_lines:
        key, _value = _parse_assignment(line)
        if key is not None and key in remaining:
            rewritten.append(f"{key}={format_env_value(remaining.pop(key))}")
        else:
            rewritten.append(line)

    if rewritten and rewritten[-1] != "":
        rewritten.append("")
    for key, value in remaining.items():
        rewritten.append(f"{key}={format_env_value(value)}")

    path.write_text("\n".join(rewritten).rstrip() + "\n", encoding="utf-8")


def format_env_value(value: str) -> str:
    """Quote values that would be ambiguous as a bare env entry."""

    if value == "" or any(character in value for character in " #\t"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _parse_assignment(raw_line: str) -> tuple[str | None, str | None]:
    stripped = raw_line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None, None

    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None, None
    return key, _unquote(raw_value.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value
