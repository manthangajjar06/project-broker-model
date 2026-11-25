"""Long-lived stdin/stdout worker for fast chart Save / list calls.

Vite keeps one process alive. Bars and the frozen model stay cached in memory,
so the second Save on the same symbol skips the multi-second CSV parse.

Each request reloads Model.manual_label (and close helpers) so logic fixes
apply without requiring a full Vite restart every time.

Protocol (one JSON object per line on stdin → one JSON line on stdout):
  {"cmd":"ping"}
  {"cmd":"list","symbol":"ABB"}
  {"cmd":"save", ...same body as /api/label...}
  {"cmd":"quit"}
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _reload_label_modules():
    """Pick up edits to path rules without killing the worker."""
    import Model.manual_label as manual_label
    import Model.run_manual_label  # noqa: F401 — keep package warm

    importlib.reload(manual_label)
    return manual_label


def _handle(message: dict) -> dict:
    cmd = str(message.get("cmd") or "").strip().lower()
    manual_label = _reload_label_modules()

    if cmd == "ping":
        return {"ok": True, "pong": True, "logic": "gap_fill_v2"}

    if cmd == "quit":
        return {"ok": True, "bye": True}

    if cmd == "list":
        symbol = str(message.get("symbol") or "").strip()
        if not symbol:
            return {"ok": False, "error": "symbol is required"}
        zones = manual_label.list_labelable_zones(symbol)
        return {
            "ok": True,
            "symbol": symbol.upper(),
            "count": len(zones),
            "zones": [manual_label.labelable_zone_to_dict(zone) for zone in zones],
        }

    if cmd == "save":
        force_label = message.get("force_label")
        saved = manual_label.save_manual_label(
            symbol=str(message["symbol"]),
            zone_start=int(message["zone_start"]),
            zone_end=int(message["zone_end"]),
            entry=float(message["entry"]),
            stop=float(message["stop"]),
            target=float(message["target"]),
            force_label=None if force_label in (None, "") else str(force_label),
        )
        return {"ok": True, "row": manual_label.saved_row_to_dict(saved)}

    return {"ok": False, "error": f"Unknown cmd {cmd!r}"}


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        message: dict | None = None
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                raise ValueError("message must be a JSON object")
            message = parsed
            payload = _handle(message)
        except Exception as error:  # noqa: BLE001 - always answer with JSON
            payload = {"ok": False, "error": str(error)}

        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

        if message is not None and str(message.get("cmd") or "").lower() == "quit":
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
