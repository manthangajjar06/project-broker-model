"""Run Step 15 from the RL directory.

    python -m Model.run_train
    python -m Model.run_train --symbols RELIANCE,TCS --timesteps 2000

A 2-hour candle that trades both the stop and the target stops and asks
in this window. Type stop or target. Answers are saved in
Model/both_touched_answers.json.
"""

from __future__ import annotations

import argparse

from Model.baseline import list_symbols
from Model.train import train


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 15 MaskablePPO training")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols. Default: every Nifty 100 file in RL/data.",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=50_000,
        help="PPO environment steps on the training years.",
    )
    args = parser.parse_args()
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    if not symbols:
        symbols = list_symbols()
    print(f"symbols {len(symbols)} timesteps {args.timesteps}", flush=True)
    path = train(symbols=symbols, total_timesteps=args.timesteps)
    if path is None:
        print("no checkpoint met the 80-90% selection rule", flush=True)
    else:
        print(path, flush=True)


if __name__ == "__main__":
    main()
