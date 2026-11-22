"""Step 15. The training contract.

Learning uses the years through 2021. Validation is 2022 and 2023.
A decision dated 2024 or later is not part of training.

The network is two layers of width 128, plus the behavior head.
The behavior loss weight is 0.1. Discount 0.99, GAE lambda 0.95,
clip 0.2, entropy coefficient 0.01, learning rate 3e-4.
Entropy stays on.

A checkpoint is kept only when, in both validation years, the trades
it rated at 80–90% bounced inside that same range, and their average R
beat that year's Step 11 baseline. The 1-minute fill is not part of this step.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


TRAIN_LAST_YEAR = 2021
VALIDATION_YEARS = (2022, 2023)
BEHAVIOR_LOSS_WEIGHT = 0.1
NET_WIDTH = (128, 128)
DISCOUNT = 0.99
GAE_LAMBDA = 0.95
CLIP = 0.2
ENTROPY = 0.01
LEARNING_RATE = 3e-4
CHANCE_LOW = 0.80
CHANCE_HIGH = 0.90

REPORT_PATH = Path(__file__).with_name("baseline_report.txt")


@dataclass(frozen=True)
class YearScore:
    """Validation result for the trades rated 80–90% in one year."""

    year: int
    bounce_rate: float | None
    average_r: float | None


def split_for(clock: datetime) -> str:
    """Train through 2021, validate on 2022 and 2023, test from 2024."""
    if clock.year <= TRAIN_LAST_YEAR:
        return "train"
    if clock.year in VALIDATION_YEARS:
        return "validation"
    return "test"


def training_log_is_clean(clocks: list[datetime]) -> bool:
    """True when every logged decision is from a training year."""
    return all(split_for(clock) == "train" for clock in clocks)


def baseline_average_r(year: int, report: str | None = None) -> float:
    """The locked 2-hour baseline, cut `all`, for one validation year."""
    text = report if report is not None else REPORT_PATH.read_text(encoding="utf-8")
    in_year = False
    in_all = False
    for line in text.splitlines():
        if line == f"year {year}":
            in_year = True
            in_all = False
            continue
        if in_year and line.startswith("year "):
            break
        if in_year and line == "cut all":
            in_all = True
            continue
        if in_year and in_all and line.startswith("cut "):
            break
        if in_all and line.startswith("average_r "):
            return float(line.split()[1])
    raise ValueError(f"the baseline report has no average R for {year}")


def keep_checkpoint(scores: list[YearScore], behavior_weight: float, report: str | None = None) -> bool:
    """The selection rule. Entropy is not turned off. A miss is not kept."""
    if behavior_weight != BEHAVIOR_LOSS_WEIGHT:
        return False
    by_year = {score.year: score for score in scores}
    if set(by_year) != set(VALIDATION_YEARS):
        return False
    for year in VALIDATION_YEARS:
        row = by_year[year]
        if row.bounce_rate is None or not (CHANCE_LOW <= row.bounce_rate <= CHANCE_HIGH):
            return False
        if row.average_r is None or not (row.average_r > baseline_average_r(year, report)):
            return False
    return True
