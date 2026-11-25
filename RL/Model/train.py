"""Step 15. Train MaskablePPO and the behavior head.

Learning uses the years through 2021. Validation is 2022 and 2023.
A decision dated 2024 or later is not part of training.

The network is two layers of width 128, plus the behavior head.
The behavior loss weight is 0.1. Discount 0.99, GAE lambda 0.95,
clip 0.2, entropy coefficient 0.01, learning rate 3e-4.
Entropy stays on.

A checkpoint is kept only when, in both validation years, the trades
it rated at 80–90% bounced inside that same range, and their average R
beat that year's Step 11 baseline. The 1-minute fill is not part of this
step. A both-touched candle stops and asks in CMD. After the model is
built, temporary 1-minute data is what justifies those answers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sb3_contrib import MaskablePPO
from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.torch_layers import FlattenExtractor

from Model.both_touched import resolve_both
from Model.broker_env import BrokerEnv, TradeLog, build_offers, load_names
from Model.environment import ACTIONS, Name, Offer
from Model.fill import BothTouched
from Model.observe import BEHAVIOR_INDEX, OBS_WIDTH
from Model.training_config import require_training_config


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
CHECKPOINT_DIR = Path(__file__).with_name("checkpoints")
CONFIG_NAME = "training_config.json"


@dataclass(frozen=True)
class YearScore:
    """Validation result for the trades rated 80–90% in one year."""

    year: int
    bounce_rate: float | None
    average_r: float | None
    trade_count: int = 0


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


def score_validation_trades(trades: Sequence[TradeLog]) -> list[YearScore]:
    """Bounce rate and average R on the 80–90% calls, per validation year."""
    scores: list[YearScore] = []
    for year in VALIDATION_YEARS:
        chosen = [
            trade
            for trade in trades
            if (trade.decided_at or trade.clock).year == year
            and trade.chance is not None
            and CHANCE_LOW <= trade.chance <= CHANCE_HIGH
            and trade.outcome in ("stop", "target", "exit", "time_stop")
            and trade.r_after_cost is not None
        ]
        if not chosen:
            scores.append(YearScore(year, None, None, 0))
            continue
        wins = sum(1 for trade in chosen if trade.outcome == "target")
        bounce = wins / len(chosen)
        average = sum(trade.r_after_cost for trade in chosen if trade.r_after_cost is not None) / len(chosen)
        scores.append(YearScore(year, bounce, average, len(chosen)))
    return scores


class BehaviorPolicy(MaskableActorCriticPolicy):
    """Two layers of width 128, plus a four-way behavior head."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "net_arch",
            dict(pi=list(NET_WIDTH), vf=list(NET_WIDTH)),
        )
        kwargs.setdefault("activation_fn", nn.Tanh)
        kwargs.setdefault("features_extractor_class", FlattenExtractor)
        super().__init__(*args, **kwargs)
        latent = NET_WIDTH[-1]
        self.behavior_head = nn.Linear(latent, len(BEHAVIOR_INDEX))

    def behavior_logits(self, obs: torch.Tensor) -> torch.Tensor:
        features = self.extract_features(obs, self.features_extractor)
        latent_pi, _latent_vf = self.mlp_extractor(features)
        return self.behavior_head(latent_pi)


class BehaviorMaskablePPO(MaskablePPO):
    """MaskablePPO with a fixed 0.1 weight on the behavior head."""

    def __init__(self, *args, behavior_weight: float = BEHAVIOR_LOSS_WEIGHT, **kwargs):
        super().__init__(*args, **kwargs)
        self.behavior_weight = behavior_weight
        self._behavior_obs: list[np.ndarray] = []
        self._behavior_labels: list[int] = []

    def add_behavior_samples(self, batch: Sequence[tuple[np.ndarray, int]]) -> None:
        for obs, label in batch:
            self._behavior_obs.append(np.asarray(obs, dtype=np.float32))
            self._behavior_labels.append(int(label))

    def train(self) -> None:
        super().train()
        if not self._behavior_obs or self.behavior_weight == 0:
            return
        policy: BehaviorPolicy = self.policy  # type: ignore[assignment]
        obs = torch.as_tensor(np.asarray(self._behavior_obs), device=self.device)
        labels = torch.as_tensor(self._behavior_labels, device=self.device, dtype=torch.long)
        logits = policy.behavior_logits(obs)
        loss = self.behavior_weight * F.cross_entropy(logits, labels)
        self.policy.optimizer.zero_grad()
        loss.backward()
        self.policy.optimizer.step()
        self._behavior_obs.clear()
        self._behavior_labels.clear()
        self.logger.record("train/behavior_loss", float(loss.detach().cpu()))


class BehaviorCallback(BaseCallback):
    """Pull resolved behavior labels out of the env after each rollout step."""

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            batch = info.get("behavior_batch") or []
            if batch and isinstance(self.model, BehaviorMaskablePPO):
                self.model.add_behavior_samples(batch)
        return True


def make_env(
    names: Sequence[Name],
    first_year: int,
    last_year: int,
    offers: Sequence[Offer] | None = None,
    ask_when_both: bool = True,
    resolve: Callable[[BothTouched], str] | None = None,
) -> BrokerEnv:
    return BrokerEnv(
        names,
        first_year,
        last_year,
        offers=offers,
        ask_when_both=ask_when_both,
        resolve=resolve or resolve_both,
    )


def build_model(env) -> BehaviorMaskablePPO:
    return BehaviorMaskablePPO(
        BehaviorPolicy,
        env,
        learning_rate=LEARNING_RATE,
        n_steps=256,
        batch_size=64,
        gamma=DISCOUNT,
        gae_lambda=GAE_LAMBDA,
        clip_range=CLIP,
        ent_coef=ENTROPY,
        verbose=1,
        policy_kwargs=dict(net_arch=dict(pi=list(NET_WIDTH), vf=list(NET_WIDTH))),
        behavior_weight=BEHAVIOR_LOSS_WEIGHT,
    )


def evaluate_policy(
    model: MaskablePPO,
    names: Sequence[Name],
    offers: Sequence[Offer],
    first_year: int,
    last_year: int,
    resolve: Callable[[BothTouched], str] | None = None,
) -> tuple[list[TradeLog], list[datetime]]:
    """Walk the window with the current weights. Greedy over the legal mask."""
    env = BrokerEnv(
        names,
        first_year,
        last_year,
        offers=offers,
        ask_when_both=True,
        resolve=resolve or resolve_both,
    )
    obs, _ = env.reset()
    done = False
    while not done:
        mask = env.action_masks()
        action, _ = model.predict(obs, action_masks=mask, deterministic=True)
        obs, _, done, _, _ = env.step(int(action))
    return env.trades, env.clocks


def save_checkpoint(model: BehaviorMaskablePPO, path: Path, kept: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    model.save(str(path / "model"))
    config = {
        "behavior_loss_weight": BEHAVIOR_LOSS_WEIGHT,
        "net_width": list(NET_WIDTH),
        "discount": DISCOUNT,
        "gae_lambda": GAE_LAMBDA,
        "clip": CLIP,
        "entropy": ENTROPY,
        "learning_rate": LEARNING_RATE,
        "train_last_year": TRAIN_LAST_YEAR,
        "validation_years": list(VALIDATION_YEARS),
        "kept": kept,
        "obs_width": OBS_WIDTH,
        "actions": list(ACTIONS),
    }
    (path / CONFIG_NAME).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def train(
    symbols: Sequence[str] | None = None,
    total_timesteps: int = 50_000,
    checkpoint_dir: Path | None = None,
    resolve: Callable[[BothTouched], str] | None = None,
) -> Path | None:
    """Train on years through 2021. Keep a checkpoint only when validation passes."""
    from Model.baseline import list_symbols

    require_training_config()
    chosen = list(symbols) if symbols else list_symbols()
    names = load_names(chosen)
    train_offers = build_offers(names, 2015, TRAIN_LAST_YEAR)
    valid_offers = build_offers(names, VALIDATION_YEARS[0], VALIDATION_YEARS[-1])
    print(f"train offers {len(train_offers)}, validation offers {len(valid_offers)}", flush=True)

    env = make_env(names, 2015, TRAIN_LAST_YEAR, offers=train_offers, resolve=resolve)
    model = build_model(env)
    model.learn(total_timesteps=total_timesteps, callback=BehaviorCallback(), progress_bar=False)

    train_clocks = list(getattr(env, "clocks", []))
    if not training_log_is_clean(train_clocks):
        raise RuntimeError("a training decision was dated 2024 or later")

    trades, _clocks = evaluate_policy(
        model,
        names,
        valid_offers,
        VALIDATION_YEARS[0],
        VALIDATION_YEARS[-1],
        resolve=resolve,
    )
    scores = score_validation_trades(trades)
    for score in scores:
        print(
            f"validation {score.year}: bounce={score.bounce_rate} "
            f"avg_r={score.average_r} n={score.trade_count}",
            flush=True,
        )
    kept = keep_checkpoint(scores, BEHAVIOR_LOSS_WEIGHT)
    out = checkpoint_dir or CHECKPOINT_DIR
    if kept:
        target = out / "selected"
        save_checkpoint(model, target, True)
        print(f"kept checkpoint {target}", flush=True)
        return target
    latest = out / "latest"
    save_checkpoint(model, latest, False)
    print(f"checkpoint not selected; wrote {latest}", flush=True)
    return None

