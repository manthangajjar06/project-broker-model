"""Write the Step 11 report once the user has supplied the capital and the charge.

Run from the RL directory:

    python -m Model.run_baseline
"""

from __future__ import annotations

from pathlib import Path

from Model.baseline import collect_validation, report_text
from Model.training_config import require_training_config


REPORT_PATH = Path(__file__).with_name("baseline_report.txt")


def main() -> None:
    config = require_training_config()
    symbols, trades = collect_validation()
    REPORT_PATH.write_text(report_text(trades, config, symbols), encoding="utf-8")
    print(REPORT_PATH)


if __name__ == "__main__":
    main()
