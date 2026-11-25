"""Build the Plan 2 Step A1 outcome dataset and write it under Model/outcome/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Model.outcome_dataset import (  # noqa: E402
    OUTCOME_DIR,
    build_dataset,
    feature_width,
    write_dataset,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan 2 Step A1 — automatic outcome dataset")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="Optional symbol list. Default: every NSE_*_2hour.csv in RL/data",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUTCOME_DIR,
        help="Output folder for outcome_rows.csv and outcome_meta.json",
    )
    args = parser.parse_args(argv)

    rows, stop_first = build_dataset(symbols=args.symbols)
    rows_path, meta_path = write_dataset(rows, folder=args.out, stop_first=stop_first)
    splits = {"train": 0, "val": 0, "test": 0}
    bounce = 0
    for row in rows:
        splits[row.split] = splits.get(row.split, 0) + 1
        bounce += row.y_bounce
    print(f"rows {len(rows)}", flush=True)
    print(f"features {feature_width()}", flush=True)
    print(f"train {splits['train']} val {splits['val']} test {splits['test']}", flush=True)
    print(f"y_bounce=1 {bounce}", flush=True)
    print(f"both_touched_stop_first {len(stop_first)}", flush=True)
    print(f"wrote {rows_path}", flush=True)
    print(f"wrote {meta_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
