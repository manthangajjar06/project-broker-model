"""Plan 2 Step A1. Automatic outcome dataset for the LightGBM bounce model.

One row per accepted zone that can arm the locked §15 plan. Features are
knowable at the zone's decision clock only. Labels come from later candles.
No hand labels except both-touched answers already on disk.

y_bounce (frozen before train):
  1 = the locked plan hit the target before the stop
  0 = stop, time stop, no-fill, expiry, cancel, or unresolved
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from Model.baseline import list_symbols
from Model.behavior import PATH_BARS, PathCandle, TakenTrade, label_path
from Model.both_touched import BatchBothTouched, resolve_both
from Model.clock import known_clock
from Model.environment import _apply_bar
from Model.fill import (
    CANCELLED,
    EXPIRY,
    HOLD,
    KEEP,
    NO_FILL,
    OPEN,
    STOP,
    TARGET,
    WORKING,
    BothTouched,
    ClosedCandle,
    Walk,
    apply_choice,
    begin,
    order_is_marketable,
)
from Model.higher import HigherBook
from Model.htf_encode import encode_htf, htf_feature_names, htf_width
from Model.load import DATA_DIR, Bar, csv_path, load_bars
from Model.memory import Memory, Record, context_of, resolution_clock
from Model.observe import CONTEXT_WIDTH, MEMORY_WIDTH, memory_vector
from Model.predict import load_frozen_model
from Model.score import accepted_zones, score_zones
from Model.snapshot import snapshot_at
from entry import Plan, required_plan


ResolveBoth = Callable[[BothTouched], str]

TRAIN_LAST_YEAR = 2021
VAL_YEARS = frozenset({2022, 2023})

# Missing feature values are filled with this before LightGBM sees the row.
MISSING = 0.0

OUTCOME_DIR = Path(__file__).with_name("outcome")
ROWS_NAME = "outcome_rows.csv"
META_NAME = "outcome_meta.json"


@dataclass(frozen=True)
class OutcomeRow:
    """One accepted zone: engineered features, bounce label, path behavior."""

    symbol: str
    decided_at: datetime
    resolved_at: datetime
    split: str
    y_bounce: int
    behavior: str
    trade_result: str | None
    p_accept: float
    plan_entry: float
    plan_stop: float
    plan_target: float
    features: tuple[float, ...]
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class _Partial:
    symbol: str
    decided_at: datetime
    resolved_at: datetime
    y_bounce: int
    behavior: str
    trade_result: str | None
    realized_r: float | None
    p_accept: float
    plan: Plan
    context: tuple[float | None, ...]
    htf: tuple[float | None, ...]
    snapshot_features: tuple[float | None, ...]


def feature_names() -> tuple[str, ...]:
    """Frozen column order for the engineered feature vector."""
    context_names = tuple(f"ctx_{index}" for index in range(CONTEXT_WIDTH))
    memory_names = (
        "mem_complete_stop_share",
        "mem_complete_stop_avg_r",
        "mem_slight_breach_share",
        "mem_slight_breach_avg_r",
        "mem_uoc_touch_share",
        "mem_uoc_touch_avg_r",
        "mem_base_never_touched_share",
        "mem_base_never_touched_avg_r",
    )
    if len(memory_names) != MEMORY_WIDTH:
        raise ValueError(f"memory name count {len(memory_names)} != {MEMORY_WIDTH}")
    return context_names + memory_names + htf_feature_names()


def feature_width() -> int:
    return CONTEXT_WIDTH + MEMORY_WIDTH + htf_width()


def split_of(year: int) -> str:
    if year <= TRAIN_LAST_YEAR:
        return "train"
    if year in VAL_YEARS:
        return "val"
    return "test"


def y_bounce_of(result: str | None) -> int:
    """Frozen label rule. Only a target fill before the stop is a bounce."""
    return 1 if result == TARGET else 0


def fill_missing(values: Sequence[float | None]) -> tuple[float, ...]:
    return tuple(MISSING if value is None or value != value else float(value) for value in values)


def build_dataset(
    symbols: Sequence[str] | None = None,
    data_dir: Path | None = None,
    resolve: ResolveBoth | None = None,
) -> tuple[tuple[OutcomeRow, ...], list[str]]:
    """Score every accepted armable zone, then attach memory in time order.

    Returns the rows and the both-touched keys that used stop-first because no
    hand answer existed yet.
    """
    folder = data_dir or DATA_DIR
    names = list(symbols) if symbols is not None else list_symbols(folder)
    batch = None
    if resolve is None:
        batch = BatchBothTouched()
        resolver: ResolveBoth = batch
    else:
        resolver = resolve
    model = load_frozen_model()
    partials: list[_Partial] = []
    total = len(names)
    print(f"outcome dataset: scoring {total} symbols", flush=True)
    for index, symbol in enumerate(names, start=1):
        print(f"{index}/{total} {symbol}", flush=True)
        bars = load_bars(csv_path(symbol, folder))
        higher = HigherBook()
        higher.run_model(symbol, bars)
        try:
            for scored in accepted_zones(score_zones(bars, model)):
                row = _partial_for(symbol, bars, scored.zone, scored.probability, higher, resolver)
                if row is not None:
                    partials.append(row)
        finally:
            higher.close_stock()
    rows = _attach_memory(partials)
    stop_first = list(batch.stop_first) if batch is not None else []
    return rows, stop_first


def rows_for_symbol(
    symbol: str,
    data_dir: Path | None = None,
    resolve: ResolveBoth | None = None,
    memory_records: Sequence[Record] = (),
) -> tuple[OutcomeRow, ...]:
    """Build rows for one symbol. Optional prior memory records for leakage tests."""
    folder = data_dir or DATA_DIR
    bars = load_bars(csv_path(symbol, folder))
    model = load_frozen_model()
    higher = HigherBook()
    higher.run_model(symbol, bars)
    resolver = resolve or resolve_both
    partials: list[_Partial] = []
    try:
        for scored in accepted_zones(score_zones(bars, model)):
            row = _partial_for(symbol, bars, scored.zone, scored.probability, higher, resolver)
            if row is not None:
                partials.append(row)
    finally:
        higher.close_stock()
    return _attach_memory(partials, seed_records=memory_records)


def features_at_decision(
    bars: Sequence[Bar],
    zone,
    plan: Plan,
    clock: datetime,
    memory: Memory,
) -> tuple[tuple[float, ...], tuple[float | None, ...]]:
    """Engineered features knowable at `clock`, plus the memory context vector."""
    snapshot = snapshot_at(bars, zone, clock)
    signal = bars[zone.end]
    atr = signal.atr_14
    context = context_of(snapshot, plan, signal.close, atr)
    if len(context) != CONTEXT_WIDTH:
        raise ValueError(f"context width is {len(context)}, expected {CONTEXT_WIDTH}")
    htf = encode_htf(bars, clock)
    summary = memory.summary(context, clock)
    mem = tuple(float(value) for value in memory_vector(summary))
    features = fill_missing(context) + mem + fill_missing(htf)
    if len(features) != feature_width():
        raise ValueError(f"feature width is {len(features)}, expected {feature_width()}")
    return features, context


def measure_locked_plan(
    bars: Sequence[Bar],
    zone,
    plan: Plan,
    symbol: str,
    resolve: ResolveBoth,
) -> tuple[int, str, str | None, float | None, datetime | None]:
    """Drive the §15 plan. Hold every bar. Returns y_bounce, behavior, result, R, resolved_at."""
    signal = bars[zone.end]
    atr = signal.atr_14
    later = bars[zone.end + 1 : zone.end + 1 + PATH_BARS]
    candles = [
        ClosedCandle(
            zone.end + offset,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            session_open=bar.time == "09:15:00",
            date=bar.date,
            time=bar.time,
        )
        for offset, bar in enumerate(later, start=1)
    ]
    behavior = _behavior_label(candles, zone, signal.close, atr)
    if atr is None or atr != atr or atr <= 0 or not (plan.stop < plan.entry):
        return 0, behavior, None, None, resolution_clock(bars, zone.end)

    walk = begin(
        plan.entry,
        plan.stop,
        plan.target,
        signal.close,
        zone.end,
        ask_when_both=True,
        symbol=symbol,
    )
    finished = None
    for candle in candles:
        if walk.phase == "done":
            break
        walk = _hold_bar(walk, candle, resolve)
        if walk.phase == "done":
            finished = candle
            break

    result = walk.result
    y = y_bounce_of(result)
    trade = _taken_trade(plan, walk, result)

    if atr is not None and atr == atr and atr > 0:
        path = [PathCandle(c.high, c.low, c.close) for c in candles]
        labeled = label_path(path, zone.uoc_low, zone.uoc_high, signal.close, atr, trade)
        behavior = labeled.label
        trade_result = labeled.trade_result
        realized_r = labeled.realized_r
    else:
        trade_result = None if trade is None else trade.result
        realized_r = None

    if finished is not None and finished.index < len(bars):
        resolved = known_clock(bars[finished.index]) or bars[finished.index].open_at()
    else:
        resolved = resolution_clock(bars, zone.end)
    return y, behavior, trade_result, realized_r, resolved


def write_dataset(
    rows: Sequence[OutcomeRow],
    folder: Path | None = None,
    stop_first: Sequence[str] = (),
) -> tuple[Path, Path]:
    """Write CSV rows and a JSON meta file with the frozen feature names."""
    out = folder or OUTCOME_DIR
    out.mkdir(parents=True, exist_ok=True)
    names = feature_names()
    rows_path = out / ROWS_NAME
    meta_path = out / META_NAME
    fieldnames = [
        "symbol",
        "decided_at",
        "resolved_at",
        "split",
        "y_bounce",
        "behavior",
        "trade_result",
        "p_accept",
        "plan_entry",
        "plan_stop",
        "plan_target",
        *names,
    ]
    with rows_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = {
                "symbol": row.symbol,
                "decided_at": row.decided_at.isoformat(sep=" "),
                "resolved_at": row.resolved_at.isoformat(sep=" "),
                "split": row.split,
                "y_bounce": row.y_bounce,
                "behavior": row.behavior,
                "trade_result": row.trade_result or "",
                "p_accept": row.p_accept,
                "plan_entry": row.plan_entry,
                "plan_stop": row.plan_stop,
                "plan_target": row.plan_target,
            }
            for name, value in zip(row.feature_names, row.features):
                payload[name] = value
            writer.writerow(payload)
    meta = {
        "feature_names": list(names),
        "feature_width": feature_width(),
        "context_width": CONTEXT_WIDTH,
        "memory_width": MEMORY_WIDTH,
        "htf_width": htf_width(),
        "missing": MISSING,
        "y_bounce": "1 if locked plan hits target before stop; else 0",
        "train_last_year": TRAIN_LAST_YEAR,
        "val_years": sorted(VAL_YEARS),
        "row_count": len(rows),
        "split_counts": _split_counts(rows),
        "both_touched_stop_first": list(stop_first),
        "both_touched_stop_first_note": (
            "Keys with no hand answer used Plan 1 stop-first. "
            "Replace via both_touched_answers.json + rebuild when 1-minute data exists."
        ),
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return rows_path, meta_path


def _partial_for(
    symbol: str,
    bars: Sequence[Bar],
    zone,
    probability: float,
    higher: HigherBook,
    resolve: ResolveBoth,
) -> _Partial | None:
    signal = bars[zone.end]
    clock = known_clock(signal)
    if clock is None:
        return None
    if not higher.allows_decision(clock):
        return None
    plan = required_plan(bars, zone, probability)
    if plan is None or not (plan.stop < plan.entry):
        return None
    y_bounce, behavior, trade_result, realized_r, resolved_at = measure_locked_plan(
        bars, zone, plan, symbol, resolve
    )
    if resolved_at is None:
        return None
    snapshot = snapshot_at(bars, zone, clock)
    atr = signal.atr_14
    context = context_of(snapshot, plan, signal.close, atr)
    if len(context) != CONTEXT_WIDTH:
        raise ValueError(f"context width is {len(context)}, expected {CONTEXT_WIDTH}")
    htf = encode_htf(bars, clock)
    return _Partial(
        symbol=symbol,
        decided_at=clock,
        resolved_at=resolved_at,
        y_bounce=y_bounce,
        behavior=behavior,
        trade_result=trade_result,
        realized_r=realized_r,
        p_accept=probability,
        plan=plan,
        context=context,
        htf=htf,
        snapshot_features=fill_missing(context),
    )


def _attach_memory(
    partials: Sequence[_Partial],
    seed_records: Sequence[Record] = (),
) -> tuple[OutcomeRow, ...]:
    names = feature_names()
    ordered = sorted(partials, key=lambda row: (row.decided_at, row.symbol))
    records = sorted(seed_records, key=lambda record: (record.resolved_at, record.decided_at, record.symbol))
    memory = Memory(records)
    pending = sorted(
        (
            Record(
                symbol=row.symbol,
                decided_at=row.decided_at,
                resolved_at=row.resolved_at,
                context=row.context,
                behavior=row.behavior,
                trade_result=row.trade_result,
                realized_r=row.realized_r,
            )
            for row in ordered
        ),
        key=lambda record: (record.resolved_at, record.decided_at, record.symbol),
    )
    cursor = 0
    rows: list[OutcomeRow] = []
    for row in ordered:
        while cursor < len(pending) and pending[cursor].resolved_at <= row.decided_at:
            memory.add(pending[cursor])
            cursor += 1
        summary = memory.summary(row.context, row.decided_at)
        mem = tuple(float(value) for value in memory_vector(summary))
        features = row.snapshot_features + mem + fill_missing(row.htf)
        if len(features) != len(names):
            raise ValueError(f"feature width is {len(features)}, expected {len(names)}")
        rows.append(
            OutcomeRow(
                symbol=row.symbol,
                decided_at=row.decided_at,
                resolved_at=row.resolved_at,
                split=split_of(row.decided_at.year),
                y_bounce=row.y_bounce,
                behavior=row.behavior,
                trade_result=row.trade_result,
                p_accept=row.p_accept,
                plan_entry=row.plan.entry,
                plan_stop=row.plan.stop,
                plan_target=row.plan.target,
                features=features,
                feature_names=names,
            )
        )
    return tuple(rows)


def _hold_bar(walk: Walk, candle: ClosedCandle, resolve: ResolveBoth) -> Walk:
    """Apply one closed candle and keep holding. Both-touched uses the answers file."""
    walk = _apply_bar(walk, candle, resolve)
    if walk.phase == WORKING:
        return apply_choice(walk, KEEP)
    if walk.phase == OPEN:
        return apply_choice(walk, HOLD)
    return walk


def _taken_trade(plan: Plan, walk: Walk, result: str | None) -> TakenTrade | None:
    if result is None:
        return None
    if result in (NO_FILL, EXPIRY, CANCELLED):
        return TakenTrade(result=result, entry=plan.entry, placed_stop=plan.stop, exit_price=None)
    if order_is_marketable(walk.entry, walk.reference_close) and walk.fill_price is not None:
        entry = walk.fill_price
    else:
        entry = plan.entry
    return TakenTrade(
        result=result,
        entry=entry,
        placed_stop=plan.stop,
        exit_price=walk.exit_price,
    )


def _behavior_label(candles, zone, decision_close: float, atr: float | None) -> str:
    from Model.behavior import UNRESOLVED

    if atr is None or atr != atr or atr <= 0:
        return UNRESOLVED
    path = [PathCandle(candle.high, candle.low, candle.close) for candle in candles]
    return label_path(path, zone.uoc_low, zone.uoc_high, decision_close, atr).label


def _split_counts(rows: Sequence[OutcomeRow]) -> dict[str, int]:
    counts = {"train": 0, "val": 0, "test": 0}
    for row in rows:
        counts[row.split] = counts.get(row.split, 0) + 1
    return counts
