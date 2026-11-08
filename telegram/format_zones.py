"""Turn scan results into readable Telegram HTML messages.

Status / app-code prompts stay plain text elsewhere. Only zone details use
HTML so labels can be bold and prices stay on their own lines on a phone.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any


def format_symbol_block(symbol: str, zones: list[dict[str, Any]]) -> str:
    """One symbol heading plus every fresh zone under it."""

    safe_symbol = html.escape(str(symbol), quote=False)
    lines = [f"<b>{safe_symbol}</b> — {len(zones)} fresh zone(s)", ""]
    for index, zone in enumerate(zones, start=1):
        lines.extend(_format_zone_lines(index, zone))
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_failures_block(failures: list[Any]) -> str:
    lines = ["<b>Failures</b>", ""]
    for failure in failures:
        symbol = html.escape(str(getattr(failure, "symbol", "?")), quote=False)
        error_type = html.escape(str(getattr(failure, "error_type", "Error")), quote=False)
        message = html.escape(str(getattr(failure, "message", "")), quote=False)
        lines.append(f"• <b>{symbol}</b>")
        lines.append(f"  {error_type}: {message}")
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def format_unresolved_block(unresolved: list[str]) -> str:
    names = ", ".join(html.escape(str(name), quote=False) for name in unresolved)
    return f"<b>No Kite token</b>\n{names}"


def _format_zone_lines(index: int, zone: dict[str, Any]) -> list[str]:
    pattern = html.escape(str(zone.get("pattern_type", "?")), quote=False)
    leg_out = html.escape(str(zone.get("leg_out_mode", "?")), quote=False)
    formed = html.escape(pretty_timestamp(zone.get("formed_at")), quote=False)
    zone_low = html.escape(_money(zone.get("zone_low")), quote=False)
    zone_high = html.escape(_money(zone.get("zone_high")), quote=False)
    entry = html.escape(_money(_entry_price(zone)), quote=False)
    label = html.escape(str((zone.get("ml") or {}).get("label", "?")).upper(), quote=False)
    probability = html.escape(_probability((zone.get("ml") or {}).get("p_accept")), quote=False)

    return [
        f"<b>#{index} {pattern} · {leg_out}</b>",
        f"Formed: {formed}",
        f"Zone: <code>{zone_low} – {zone_high}</code>",
        f"Entry: <code>{entry}</code>",
        f"ML: <b>{label}</b> ({probability})",
    ]


def pretty_timestamp(value: Any) -> str:
    """Show dates like ``02 Feb 2026, 15:15`` when the value is ISO-like."""

    if value is None:
        return "?"
    text = str(value).strip()
    if not text:
        return "?"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.strftime("%d %b %Y, %H:%M")


def _entry_price(zone: dict[str, Any]) -> Any:
    entry = zone.get("entry")
    if isinstance(entry, dict):
        return entry.get("final_entry")
    return None


def _money(value: Any) -> str:
    if value is None:
        return "?"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _probability(value: Any) -> str:
    if value is None:
        return "?"
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return str(value)
