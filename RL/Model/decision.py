"""Step 8. The choice at the zone.

The model may skip, or take the one plan from entry.py.
The prices are fixed at the zone close. A later candle cannot move them.
Take is masked until the 6th session, when entry.py rejects the zone,
and when the stop is not strictly below the entry.
Skip is always available.
"""

from __future__ import annotations

from dataclasses import dataclass

from Model.load import Bar
from Model.zones import Zone
from entry import Plan, entry_is_due, required_plan


SKIP = "skip"
TAKE = "take"


@dataclass(frozen=True)
class Decision:
    prices: Plan | None
    take_allowed: bool
    skip_allowed: bool


def prices_at_close(bars: list[Bar], zone: Zone, probability: float) -> Plan | None:
    """The entry, stop, and target, computed once from the candles that have closed."""
    return required_plan(bars, zone, probability)


def session_is_due(bars: list[Bar], zone: Zone, on_date: str) -> bool:
    """Day 1 is the zone's last candle. Take is offered on day 6 or later."""
    return entry_is_due(bars, zone, on_date)


def stop_is_strictly_below_entry(plan: Plan) -> bool:
    """A long needs the stop under the entry. Otherwise the take is masked."""
    return plan.stop < plan.entry


def take_is_allowed(plan: Plan | None, due: bool) -> bool:
    """Take is allowed only when a plan exists, the session is due, and the stop is below the entry."""
    if plan is None:
        return False
    if not due:
        return False
    if not stop_is_strictly_below_entry(plan):
        return False
    return True


def skip_is_allowed() -> bool:
    """Skip is always available, including when take is masked."""
    return True


def build_decision(bars: list[Bar], zone: Zone, probability: float, on_date: str) -> Decision:
    """Lock the prices, then say whether take is allowed on this session."""
    prices = prices_at_close(bars, zone, probability)
    due = session_is_due(bars, zone, on_date)
    return Decision(
        prices=prices,
        take_allowed=take_is_allowed(prices, due),
        skip_allowed=skip_is_allowed(),
    )
