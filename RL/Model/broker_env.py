"""Gymnasium wrapper around the pauseable calendar walk.

Illegal actions cannot be sampled. A both-touched candle stops and asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from Model.both_touched import resolve_both
from Model.calendar_walk import CalendarWalk
from Model.decision import SKIP, TAKE
from Model.environment import ACTIONS, Moment, Name, Offer, StepRecord, collect_offers
from Model.fill import BothTouched
from Model.memory import Memory, Record
from Model.observe import OBS_WIDTH, behavior_id, observation_of
from Model.reward import PaperBook
from Model.training_config import require_training_config


ActionIndex = {action: index for index, action in enumerate(ACTIONS)}


@dataclass
class TradeLog:
    """One closed trade, for validation scoring."""

    symbol: str
    clock: datetime
    chance: float | None
    outcome: str
    r_after_cost: float | None
    behavior: str | None
    decided_at: datetime | None = None


class BrokerEnv(gym.Env):
    """One paper account. reset() starts a year window; step() is one event."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        names: Sequence[Name],
        first_year: int,
        last_year: int,
        offers: Sequence[Offer] | None = None,
        records: Sequence[Record] = (),
        ask_when_both: bool = True,
        resolve: Callable[[BothTouched], str] | None = None,
    ):
        super().__init__()
        self.names = list(names)
        self.first_year = first_year
        self.last_year = last_year
        self.offers = list(offers) if offers is not None else None
        self.seed_records = list(records)
        self.ask_when_both = ask_when_both
        self.resolve = resolve or resolve_both
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(OBS_WIDTH,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(len(ACTIONS))
        self.calendar: CalendarWalk | None = None
        self.moment: Moment | None = None
        self._last_obs = np.zeros(OBS_WIDTH, dtype=np.float32)
        self.trades: list[TradeLog] = []
        self.behavior_batch: list[tuple[np.ndarray, int]] = []
        self.clocks: list[datetime] = []

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        config = require_training_config()
        book = PaperBook(config.starting_capital, config.charge)
        self.calendar = CalendarWalk(
            self.names,
            book,
            self.first_year,
            self.last_year,
            offers=self.offers,
            records=self.seed_records,
            ask_when_both=self.ask_when_both,
            resolve_both=self.resolve,
        )
        self.trades = []
        self.behavior_batch = []
        self.clocks = []
        self.moment = self.calendar.start()
        self._last_obs = self._observe(self.moment)
        return self._last_obs, {"action_mask": self.action_masks()}

    def action_masks(self) -> np.ndarray:
        if self.moment is None:
            return np.ones(len(ACTIONS), dtype=bool)
        return np.asarray(
            [bool(self.moment.mask.get(action, False)) for action in ACTIONS],
            dtype=bool,
        )

    def step(self, action: int):
        assert self.calendar is not None
        if self.moment is None:
            return self._last_obs, 0.0, True, False, {"action_mask": self.action_masks()}
        name = ACTIONS[int(action)]
        decision_obs = self._last_obs.copy()
        result = self.calendar.act(name)
        if name in (SKIP, TAKE):
            self.clocks.append(self.moment.clock)
        fresh: list[tuple[np.ndarray, int]] = []
        self._note_closed(result.record, decision_obs, fresh)
        for side in result.side:
            self._note_closed(side, decision_obs, fresh)
        self.behavior_batch.extend(fresh)
        self.moment = result.moment
        obs = self._observe(self.moment)
        self._last_obs = obs
        info = {
            "action_mask": self.action_masks(),
            "behavior_batch": fresh,
            "record": result.record,
        }
        return obs, float(result.reward), result.done, False, info

    def _note_closed(
        self,
        record: StepRecord | None,
        decision_obs: np.ndarray,
        fresh: list[tuple[np.ndarray, int]],
    ) -> None:
        if record is None:
            return
        if record.behavior is not None:
            sample = (decision_obs, behavior_id(record.behavior))
            fresh.append(sample)
            self.behavior_batch.append(sample)
        if record.action in ("stop", "target", "exit", "time_stop", "cancel", "expiry", "no_fill"):
            decided = record.decided_at or record.clock
            self.trades.append(
                TradeLog(
                    record.symbol,
                    decided,
                    record.chance,
                    record.action,
                    record.reward.r_after_cost,
                    record.behavior,
                    decided,
                )
            )

    def _observe(self, moment: Moment | None) -> np.ndarray:
        if moment is None or self.calendar is None:
            return np.zeros(OBS_WIDTH, dtype=np.float32)
        atr = None
        close = 0.0
        if moment.offer is not None:
            bars = self.calendar.by_symbol[moment.symbol]
            close = bars[moment.offer.zone.end].close
            atr = bars[moment.offer.zone.end].atr_14
        return observation_of(
            moment.snapshot,
            moment.plan,
            close,
            atr,
            self.calendar.memory,
            moment.clock,
        )


def load_names(symbols: Sequence[str]) -> list[Name]:
    from Model.load import csv_path, load_bars

    names = []
    for symbol in symbols:
        print(f"load {symbol}", flush=True)
        names.append(Name(symbol, load_bars(csv_path(symbol))))
    return names


def build_offers(names: Sequence[Name], first_year: int, last_year: int) -> list[Offer]:
    print(f"collect offers {first_year}-{last_year} on {len(names)} names", flush=True)
    return collect_offers(names, first_year, last_year)
