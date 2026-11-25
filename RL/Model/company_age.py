"""Company-age gate for manual labeling and future training filters.

A stock may be labeled only after it has more than three years of history
in RL/data. Age is measured from the first candle date in the CSV to the
zone decision date (the date of the zone's last 2-hour candle).
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from Model.load import Bar


# Locked rule: company must be older than this many calendar years.
MIN_COMPANY_YEARS = 3


def add_calendar_years(day: date, years: int) -> date:
    """Move a calendar date forward by whole years.

    February 29 rolls to February 28 when the target year is not a leap year.
    """
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def first_bar_date(bars: Sequence[Bar]) -> date | None:
    """The calendar date of the oldest bar in this file."""
    if not bars:
        return None
    return date.fromisoformat(bars[0].date)


def company_is_old_enough(
    first: date | None,
    decision: date | None,
    years: int = MIN_COMPANY_YEARS,
) -> bool:
    """True when decision is strictly after first + years.

    Example: first bar 2015-02-02 → ready from 2018-02-03 onward.
    """
    if first is None or decision is None:
        return False
    ready_after = add_calendar_years(first, years)
    return decision > ready_after


def bars_allow_labeling(bars: Sequence[Bar], decision_date: str) -> bool:
    """Convenience check from a bar list and an ISO decision date string."""
    first = first_bar_date(bars)
    try:
        decision = date.fromisoformat(decision_date[:10])
    except ValueError:
        return False
    return company_is_old_enough(first, decision)
