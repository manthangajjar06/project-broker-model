"""Step 13. The reward is the change in the paper book.

No order is sent to a broker. The stop risks 1% of equity at the decision.
Shares are a whole number. Skip, cancel, expiry, and no-fill score 0.
A filled trade scores its rupee change divided by equity at the decision.
There is no bonus for a zone that looks good.

R is the same rupee change divided by the planned risk, after slippage and
the Zerodha delivery charge. A 09:15 gap exit does not take exit slippage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from Model.baseline import ChargeSchedule, filled_prices, r_after_cost, sized_shares, trade_pnl
from Model.fill import Walk
from Model.memory import Memory


# These outcomes never open a position, so the book does not move.
ZERO_OUTCOMES = ("skip", "cancel", "expiry", "no_fill")

TARGET_BEFORE_STOP = "target"


@dataclass(frozen=True)
class Reward:
    """What the policy is taught for one decision."""

    outcome: str
    equity_before: float
    equity_after: float
    pnl: float
    reward: float
    r_after_cost: float | None
    shares: int


class PaperBook:
    """One paper account. The balance carries from one decision to the next."""

    def __init__(self, equity: float, charge: ChargeSchedule):
        if equity <= 0:
            raise ValueError("the paper book starts with a positive balance")
        self.equity = equity
        self.charge = charge

    def mark(
        self,
        outcome: str,
        plan_entry: float,
        plan_stop: float,
        raw_entry: float | None,
        raw_exit: float | None,
        atr: float,
        gap_exit: bool = False,
    ) -> Reward:
        """Apply one outcome and return the reward scored at the old equity."""
        scored = score_decision(
            self.equity,
            self.charge,
            outcome,
            plan_entry,
            plan_stop,
            raw_entry,
            raw_exit,
            atr,
            gap_exit,
        )
        self.equity = scored.equity_after
        return scored


def score_decision(
    equity: float,
    charge: ChargeSchedule,
    outcome: str,
    plan_entry: float,
    plan_stop: float,
    raw_entry: float | None,
    raw_exit: float | None,
    atr: float,
    gap_exit: bool = False,
) -> Reward:
    """The reward for this decision. Equity is the balance before it."""
    if outcome in ZERO_OUTCOMES:
        return Reward(outcome, equity, equity, 0.0, 0.0, None, 0)

    shares = sized_shares(equity, equity, plan_entry, plan_stop, atr, raw_entry)
    if shares < 1 or raw_entry is None or raw_exit is None:
        return Reward(outcome, equity, equity, 0.0, 0.0, None, 0)

    pnl = trade_pnl(raw_entry, raw_exit, atr, shares, charge, gap_exit)
    equity_after = round(equity + pnl, 2)
    reward = pnl / equity
    realized_r = r_after_cost(
        plan_entry,
        plan_stop,
        raw_entry,
        raw_exit,
        atr,
        shares,
        charge,
        gap_exit,
    )
    return Reward(outcome, equity, equity_after, pnl, reward, realized_r, shares)


def score_walk(
    equity: float,
    charge: ChargeSchedule,
    outcome: str,
    walk: Walk,
    atr: float,
) -> Reward:
    """Score a finished Step 9 walk. The fill prices come from that walk.

    A 09:15 open through the stop or the target keeps that open. The walk
    marks it, and this score does not take exit slippage a second time.
    """
    raw_entry, raw_exit = filled_prices(walk)
    return score_decision(
        equity,
        charge,
        outcome,
        walk.entry,
        walk.stop,
        raw_entry,
        raw_exit,
        atr,
        walk.gap_exit,
    )


def stated_chance(outcomes: Sequence[str]) -> float:
    """The share of resolved plans that reached the target before the stop.

    A plan that has not resolved yet is left out of the count. The chance
    is that share. It does not change the fill or the reward.
    """
    resolved = [outcome for outcome in outcomes if outcome != "unresolved"]
    if not resolved:
        raise ValueError("a stated chance needs at least one resolved plan")
    hits = sum(1 for outcome in resolved if outcome == TARGET_BEFORE_STOP)
    return hits / len(resolved)


def stated_chance_from_memory(memory: Memory, at: datetime) -> float:
    """The chance read from similar plans whose outcome is already known.

    A record that resolves after `at` is hidden. A record with no trade
    result has not reached the target or the stop, so it is left out.
    """
    known = []
    for record in memory.visible(at):
        if record.trade_result is None or record.trade_result == "unresolved":
            continue
        known.append(record.trade_result)
    return stated_chance(known)
