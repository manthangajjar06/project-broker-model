"""CLI bridge for the chart label API.

Examples
--------
List accepted zones (JSON on stdout):

    python -m Model.run_manual_label list --symbol RELIANCE

Save one manual label (JSON body on stdin or --json file):

    python -m Model.run_manual_label save --stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow `python -m Model.run_manual_label` from the RL folder.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Model.manual_label import (  # noqa: E402
    labelable_zone_to_dict,
    list_labelable_zones,
    save_manual_label,
    saved_row_to_dict,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual zone labeling for dataset.csv")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List accepted zones older than 3 years")
    list_parser.add_argument("--symbol", required=True)

    save_parser = sub.add_parser("save", help="Save one manual Entry/Stop/Target row")
    save_parser.add_argument("--stdin", action="store_true", help="Read JSON body from stdin")
    save_parser.add_argument("--json", type=Path, help="Path to a JSON body file")
    save_parser.add_argument("--symbol")
    save_parser.add_argument("--zone-start", type=int)
    save_parser.add_argument("--zone-end", type=int)
    save_parser.add_argument("--entry", type=float)
    save_parser.add_argument("--stop", type=float)
    save_parser.add_argument("--target", type=float)

    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            zones = list_labelable_zones(args.symbol)
            payload = {
                "ok": True,
                "symbol": args.symbol.upper(),
                "count": len(zones),
                "zones": [labelable_zone_to_dict(zone) for zone in zones],
            }
            print(json.dumps(payload))
            return 0

        body = _load_save_body(args)
        force_label = body.get("force_label")
        saved = save_manual_label(
            symbol=str(body["symbol"]),
            zone_start=int(body["zone_start"]),
            zone_end=int(body["zone_end"]),
            entry=float(body["entry"]),
            stop=float(body["stop"]),
            target=float(body["target"]),
            force_label=None if force_label in (None, "") else str(force_label),
        )
        print(json.dumps({"ok": True, "row": saved_row_to_dict(saved)}))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI must always return JSON
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


def _load_save_body(args: argparse.Namespace) -> dict:
    if args.stdin:
        raw = sys.stdin.read()
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError("stdin JSON must be an object")
        return body

    if args.json is not None:
        body = json.loads(args.json.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            raise ValueError("JSON file must contain an object")
        return body

    missing = [
        name
        for name, value in (
            ("symbol", args.symbol),
            ("zone_start", args.zone_start),
            ("zone_end", args.zone_end),
            ("entry", args.entry),
            ("stop", args.stop),
            ("target", args.target),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"Missing save fields: {', '.join(missing)}")

    return {
        "symbol": args.symbol,
        "zone_start": args.zone_start,
        "zone_end": args.zone_end,
        "entry": args.entry,
        "stop": args.stop,
        "target": args.target,
    }


if __name__ == "__main__":
    raise SystemExit(main())
