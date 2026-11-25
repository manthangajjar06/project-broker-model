"""Manual Entry / Stop / Target labeling → RL/Model/dataset.csv.

Flow
----
1. User picks an accepted zone on a stock that is older than 3 years.
2. User types Entry, Stop, and Target (target is always human).
3. Code builds the same engineered features as Plan 2 (snapshot, footprint
   summaries, daily/weekly/monthly, HTF windows, memory placeholders).
4. Code walks later candles and writes an automatic outcome label:

     premature_entry  entry fill then target inside sessions 1..5
                      (before the normal day-6 entry window)
     nothing          stop traded before any entry fill in that
                      early window (we would not have taken it yet)
     win              after day 6, filled and target before stop
     loss             filled and stop before target (early or armed)
     no_fill          limit never filled in the path window
     unresolved       path ended without a clear result

Open at/below entry (still above stop) counts as an entry fill.

One training file only: dataset.csv next to this package.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from Model.behavior import PathCandle, label_path
from Model.clock import known_clock
from Model.company_age import bars_allow_labeling, company_is_old_enough, first_bar_date
from Model.fill import ClosedCandle
from Model.higher import HigherBook
from Model.load import Bar, csv_path, load_bars
from Model.memory import Memory, resolution_clock
from Model.outcome_dataset import (
    MISSING,
    feature_names,
    features_at_decision,
    split_of,
)
from Model.predict import ACCEPT_AT, load_frozen_model, predict_probability, score_label
from Model.score import (
    ScoredZone,
    accepted_zones,
    daily_atr,
    entry_price,
    features_for,
    score_zones,
    true_range_and_atr,
)
from Model.zones import find_zones
from entry import ENTRY_ON_SESSION, Plan, required_plan


MODEL_DIR = Path(__file__).resolve().parent
DATASET_PATH = MODEL_DIR / "dataset.csv"
DATASET_META_PATH = MODEL_DIR / "dataset_meta.json"

LABEL_WIN = "win"
LABEL_LOSS = "loss"
LABEL_PREMATURE = "premature_entry"
LABEL_NOTHING = "nothing"
LABEL_NO_FILL = "no_fill"
LABEL_UNRESOLVED = "unresolved"
LABEL_BAD_ENTRY = "bad_entry"

# Sessions 1..5 are early. Session 1 = zone signal date. Entry arms on session 6.
EARLY_LAST_SESSION = ENTRY_ON_SESSION - 1

# Manual labeling walks the full remaining series after the signal.
# A fixed 40/400-bar cutoff was wrongly labeling late retests as no_fill
# (e.g. 2021 zone filled on 2024-11-27).
MANUAL_PATH_BARS = None  # None = through the last bar


@dataclass(frozen=True)
class PathOutcome:
    """Automatic label from the candles after the decision."""

    label: str
    behavior: str
    y_bounce: int
    resolved_at: datetime | None
    filled: bool
    notes: str


@dataclass(frozen=True)
class LabelableZone:
    """One accepted zone the chart may offer for manual prices."""

    symbol: str
    zone_start: int
    zone_end: int
    pattern: str
    leg_out_mode: str
    decided_at: str
    p_accept: float
    suggested_entry: float | None
    suggested_stop: float | None
    suggested_target: float | None
    uoc_low: float
    uoc_high: float


@dataclass(frozen=True)
class SavedRow:
    """What was written (or updated) in dataset.csv."""

    symbol: str
    decided_at: str
    outcome_label: str
    y_bounce: int
    behavior: str
    entry: float
    stop: float
    target: float
    path: str
    updated: bool


@dataclass(frozen=True)
class _EarlyHit:
    label: str
    candle_index: int
    touched_entry: bool
    notes: str


@dataclass(frozen=True)
class _EarlyScan:
    """Early-window result: a resolved hit, and/or an open fill to carry forward."""

    hit: _EarlyHit | None
    filled: bool


@dataclass(frozen=True)
class _ArmedHit:
    label: str
    candle_index: int
    notes: str


def list_labelable_zones(symbol: str) -> list[LabelableZone]:
    """Accepted zones on this symbol whose decision is after the 3-year gate."""
    bars = load_bars(csv_path(symbol))
    if not bars:
        return []

    first = first_bar_date(bars)
    model = load_frozen_model()
    higher = HigherBook()
    higher.run_model(symbol, bars)

    found: list[LabelableZone] = []
    try:
        for scored in accepted_zones(score_zones(bars, model)):
            zone = scored.zone
            signal = bars[zone.end]
            clock = known_clock(signal)
            if clock is None:
                continue
            if not company_is_old_enough(first, clock.date()):
                continue
            if not higher.allows_decision(clock):
                continue

            plan = required_plan(bars, zone, scored.probability)
            found.append(
                LabelableZone(
                    symbol=symbol.upper(),
                    zone_start=zone.start,
                    zone_end=zone.end,
                    pattern=zone.pattern,
                    leg_out_mode=zone.leg_out_mode,
                    decided_at=clock.strftime("%Y-%m-%d %H:%M:%S"),
                    p_accept=scored.probability,
                    suggested_entry=None if plan is None else plan.entry,
                    suggested_stop=None if plan is None else plan.stop,
                    suggested_target=None if plan is None else plan.target,
                    uoc_low=zone.uoc_low,
                    uoc_high=zone.uoc_high,
                )
            )
    finally:
        higher.close_stock()

    found.sort(key=lambda row: (row.decided_at, row.zone_start))
    return found


def save_manual_label(
    symbol: str,
    zone_start: int,
    zone_end: int,
    entry: float,
    stop: float,
    target: float,
    dataset_path: Path | None = None,
    force_label: str | None = None,
) -> SavedRow:
    """Build features, auto-label the path, upsert one row in dataset.csv.

    force_label:
      None       → automatic path label (win / loss / premature_entry / …)
      bad_entry  → human skip; still stores features + prices for the record
    """
    symbol = symbol.upper().strip()
    path = dataset_path or DATASET_PATH

    if not (stop < entry < target):
        raise ValueError(
            f"Prices must satisfy stop < entry < target. "
            f"Got stop={stop}, entry={entry}, target={target}."
        )

    if force_label is not None and force_label != LABEL_BAD_ENTRY:
        raise ValueError(f"Unsupported force_label {force_label!r}")

    bars = load_bars(csv_path(symbol))
    if not bars:
        raise ValueError(f"No bars for {symbol}")
    if zone_end >= len(bars) or zone_start < 0 or zone_start >= zone_end:
        raise ValueError(f"Bad zone indices start={zone_start} end={zone_end}")

    model = load_frozen_model()
    scored_match = _find_accepted_zone(bars, model, zone_start, zone_end)
    if scored_match is None:
        raise ValueError(
            f"{symbol} zone {zone_start}-{zone_end} is not an accepted zone "
            f"(p_accept >= {ACCEPT_AT})."
        )

    zone = scored_match.zone
    signal = bars[zone.end]
    clock = known_clock(signal)
    if clock is None:
        raise ValueError("Zone has no regular decision clock (Muhurat / odd bar).")

    if not bars_allow_labeling(bars, signal.date):
        raise ValueError(
            f"{symbol} is not older than 3 years at {signal.date}. "
            "Labeling is blocked until the company has more than 3 years of data."
        )

    # HigherBook warmup already matched the chart's 3-year gate for labeling.
    # Skipping the full HTF book rebuild here keeps Save responsive.

    plan = Plan(entry=float(entry), stop=float(stop), target=float(target))
    memory = Memory(())
    features, _context = features_at_decision(bars, zone, plan, clock, memory)
    names = feature_names()
    if len(features) != len(names):
        raise ValueError(f"Feature width {len(features)} != {len(names)}")

    if force_label == LABEL_BAD_ENTRY:
        outcome = PathOutcome(
            label=LABEL_BAD_ENTRY,
            behavior="skipped",
            y_bounce=0,
            resolved_at=clock,
            filled=False,
            notes="Human marked this zone as a bad entry / skip.",
        )
    else:
        outcome = label_manual_path(bars, zone, plan, symbol)
    if outcome.resolved_at is None:
        raise ValueError("Could not resolve a path end time for this zone.")

    row = {
        "symbol": symbol,
        "decided_at": clock.strftime("%Y-%m-%d %H:%M:%S"),
        "resolved_at": outcome.resolved_at.strftime("%Y-%m-%d %H:%M:%S"),
        "split": split_of(clock.year),
        "zone_start": zone.start,
        "zone_end": zone.end,
        "pattern": zone.pattern,
        "leg_out_mode": zone.leg_out_mode,
        "p_accept": scored_match.probability,
        "entry": plan.entry,
        "stop": plan.stop,
        "target": plan.target,
        "outcome_label": outcome.label,
        "y_bounce": outcome.y_bounce,
        "behavior": outcome.behavior,
        "path_notes": outcome.notes,
        "source": "manual_skip" if force_label == LABEL_BAD_ENTRY else "manual",
    }
    for name, value in zip(names, features):
        row[name] = value

    updated = _upsert_dataset_row(path, row, names)
    _write_dataset_meta(path, names)

    return SavedRow(
        symbol=symbol,
        decided_at=row["decided_at"],
        outcome_label=outcome.label,
        y_bounce=outcome.y_bounce,
        behavior=outcome.behavior,
        entry=plan.entry,
        stop=plan.stop,
        target=plan.target,
        path=str(path),
        updated=updated,
    )


def label_manual_path(
    bars: Sequence[Bar],
    zone,
    plan: Plan,
    symbol: str,
) -> PathOutcome:
    """Walk later candles with the 6-session early window rules.

    After day 6 the limit stays armed until fill / stop / target for the
    rest of the series (no fixed bar expiry — late retests still count).
    """
    del symbol  # reserved for future both-touched keys
    signal = bars[zone.end]
    signal_date = signal.date
    atr = signal.atr_14

    later = bars[zone.end + 1 :]
    if MANUAL_PATH_BARS is not None:
        later = later[:MANUAL_PATH_BARS]
    candles = [
        ClosedCandle(
            index=zone.end + offset,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            session_open=bar.time == "09:15:00",
            date=bar.date,
            time=bar.time,
        )
        for offset, bar in enumerate(later, start=1)
    ]

    behavior = _behavior_only(candles, zone, signal.close, atr)

    early = _scan_early_window(candles, plan, signal_date)
    if early.hit is not None:
        resolved = _resolved_at(bars, early.hit.candle_index, zone.end)
        return PathOutcome(
            label=early.hit.label,
            behavior=behavior,
            y_bounce=0,
            resolved_at=resolved,
            filled=early.hit.touched_entry,
            notes=early.hit.notes,
        )

    armed = _first_index_on_or_after_session(candles, signal_date, ENTRY_ON_SESSION)
    if armed is None:
        return PathOutcome(
            label=LABEL_UNRESOLVED,
            behavior=behavior,
            y_bounce=0,
            resolved_at=resolution_clock(bars, zone.end),
            filled=early.filled,
            notes="Path ended before session 6; no armed entry.",
        )

    # If entry already filled in sessions 1..5 without target/stop, the trade
    # stays open into day 6+ — do not wait for a second fill (that caused
    # false no_fill when price never revisited entry).
    hit = _walk_armed_limit(candles[armed:], plan, already_filled=early.filled)
    if hit is None:
        resolved = resolution_clock(bars, zone.end)
        if resolved is None and candles:
            resolved = _resolved_at(bars, candles[-1].index, zone.end)
        return PathOutcome(
            label=LABEL_NO_FILL if not early.filled else LABEL_UNRESOLVED,
            behavior=behavior,
            y_bounce=0,
            resolved_at=resolved,
            filled=early.filled,
            notes=(
                f"Entry never traded in the remaining {len(candles)} bars after "
                f"the signal (armed from session {ENTRY_ON_SESSION})."
                if not early.filled
                else (
                    f"Filled before day {ENTRY_ON_SESSION} but neither stop nor "
                    "target traded afterward."
                )
            ),
        )

    resolved = _resolved_at(bars, hit.candle_index, zone.end)
    return PathOutcome(
        label=hit.label,
        behavior=behavior,
        y_bounce=1 if hit.label == LABEL_WIN else 0,
        resolved_at=resolved,
        filled=True,
        notes=hit.notes,
    )


def _entry_fills(candle: ClosedCandle, plan: Plan) -> bool:
    """True when the long limit fills on this bar.

    Counts:
      - bar range trades the entry price
      - open at/below entry but still above stop (gap / opened through the limit)
    """
    if candle.low <= plan.entry <= candle.high:
        return True
    if plan.stop < candle.open <= plan.entry:
        return True
    return False


def _resolve_after_fill(
    candle: ClosedCandle,
    plan: Plan,
    *,
    win_label: str,
    filled_note: str,
    ignore_stop: bool = False,
    ignore_target: bool = False,
) -> _ArmedHit | None:
    """After a fill: target → win_label, stop → loss (stop-first if both).

    Same-bar path assumptions on the fill candle:
      - open below entry → dip before reclaim is not a stop
      - open above entry → high before the dip-fill is not a target
        (e.g. opened above target, sold through entry)
    """
    traded_stop = (not ignore_stop) and candle.low <= plan.stop
    traded_target = (not ignore_target) and candle.high >= plan.target
    if traded_stop and traded_target:
        return _ArmedHit(
            label=LABEL_LOSS,
            candle_index=candle.index,
            notes=(
                f"{filled_note} on {candle.date} {candle.time}; "
                "same bar traded stop and target → stop-first loss."
            ),
        )
    if traded_stop:
        return _ArmedHit(
            label=LABEL_LOSS,
            candle_index=candle.index,
            notes=f"{filled_note} then stop on {candle.date} {candle.time}.",
        )
    if traded_target:
        return _ArmedHit(
            label=win_label,
            candle_index=candle.index,
            notes=f"{filled_note} then target on {candle.date} {candle.time}.",
        )
    return None


def _walk_armed_limit(
    candles: Sequence[ClosedCandle],
    plan: Plan,
    *,
    already_filled: bool = False,
) -> _ArmedHit | None:
    """After day 6: wait for entry fill (unless already filled), then stop or target.

    No bar expiry. Stop-first if the same bar trades both stop and target.
    Returns None when the entry is never traded in this window.
    """
    filled = already_filled

    for candle in candles:
        if not filled:
            if not _entry_fills(candle, plan):
                continue
            filled = True
            # Open below entry → ignore pre-fill stop wick.
            # Open above entry → ignore pre-fill high (not a post-fill target).
            hit = _resolve_after_fill(
                candle,
                plan,
                win_label=LABEL_WIN,
                filled_note="Filled",
                ignore_stop=candle.open < plan.entry,
                ignore_target=candle.open > plan.entry,
            )
            if hit is not None:
                return hit
            continue

        hit = _resolve_after_fill(
            candle,
            plan,
            win_label=LABEL_WIN,
            filled_note="Open trade",
        )
        if hit is not None:
            return hit

    return None


def _scan_early_window(
    candles: Sequence[ClosedCandle],
    plan: Plan,
    signal_date: str,
) -> _EarlyScan:
    """Inspect sessions 1..5. Signal date is session 1.

    Rules (simple):
      - stop before any entry fill → nothing (would not take the trade yet)
      - after entry fill → target = premature_entry, stop = loss
      - open below entry counts as a fill; same-bar stop wick is ignored
      - fill without stop/target → filled=True so day-6+ keeps the open trade
    """
    filled = False
    seen_dates: list[str] = [signal_date]

    for candle in candles:
        if candle.date < signal_date:
            continue
        if candle.date != seen_dates[-1]:
            seen_dates.append(candle.date)

        session = len(seen_dates)
        if session > EARLY_LAST_SESSION:
            break

        if not filled:
            if _entry_fills(candle, plan):
                filled = True
                hit = _resolve_after_fill(
                    candle,
                    plan,
                    win_label=LABEL_PREMATURE,
                    filled_note="Filled",
                    ignore_stop=candle.open < plan.entry,
                    ignore_target=candle.open > plan.entry,
                )
                if hit is not None:
                    return _EarlyScan(
                        hit=_EarlyHit(
                            label=hit.label,
                            candle_index=hit.candle_index,
                            touched_entry=True,
                            notes=(
                                f"{hit.notes} (session {session}, before day "
                                f"{ENTRY_ON_SESSION})."
                            ),
                        ),
                        filled=True,
                    )
                continue

            # Stop without a fill voids the early window.
            if candle.low <= plan.stop:
                return _EarlyScan(
                    hit=_EarlyHit(
                        label=LABEL_NOTHING,
                        candle_index=candle.index,
                        touched_entry=False,
                        notes=(
                            f"Stop traded on session {session} before entry fill "
                            f"(before day {ENTRY_ON_SESSION}). Labeled nothing."
                        ),
                    ),
                    filled=False,
                )
            continue

        hit = _resolve_after_fill(
            candle,
            plan,
            win_label=LABEL_PREMATURE,
            filled_note="Open trade",
        )
        if hit is not None:
            return _EarlyScan(
                hit=_EarlyHit(
                    label=hit.label,
                    candle_index=hit.candle_index,
                    touched_entry=True,
                    notes=(
                        f"{hit.notes} (session {session}, before day "
                        f"{ENTRY_ON_SESSION})."
                    ),
                ),
                filled=True,
            )

    return _EarlyScan(hit=None, filled=filled)


def _first_index_on_or_after_session(
    candles: Sequence[ClosedCandle],
    signal_date: str,
    session_needed: int,
) -> int | None:
    """Index into `candles` for the first bar on session `session_needed` or later."""
    seen_dates: list[str] = [signal_date]
    for index, candle in enumerate(candles):
        if candle.date < signal_date:
            continue
        if candle.date != seen_dates[-1]:
            seen_dates.append(candle.date)
        if len(seen_dates) >= session_needed:
            return index
    return None


def _find_accepted_zone(bars, model, zone_start: int, zone_end: int):
    """Score only the matching geometry — avoid scoring every zone on Save."""
    match = None
    for zone in find_zones(bars):
        if zone.start == zone_start and zone.end == zone_end:
            match = zone
            break
    if match is None:
        return None

    true_range, atr = true_range_and_atr(bars)
    probability = predict_probability(model, features_for(bars, match, true_range, atr))
    if score_label(probability) != "accepted":
        return None

    base = bars[match.start + 1]
    leg_out = bars[match.start + 2]
    datr = daily_atr(bars).get(base.date)
    entry, warning = entry_price(base, leg_out, datr)
    return ScoredZone(match, probability, "accepted", entry, warning)


def _behavior_only(candles, zone, decision_close: float, atr: float | None) -> str:
    from Model.behavior import UNRESOLVED

    if atr is None or atr != atr or atr <= 0:
        return UNRESOLVED
    path = [PathCandle(c.high, c.low, c.close) for c in candles]
    return label_path(path, zone.uoc_low, zone.uoc_high, decision_close, atr).label


def _resolved_at(bars: Sequence[Bar], bar_index: int, zone_end: int) -> datetime | None:
    if 0 <= bar_index < len(bars):
        return known_clock(bars[bar_index]) or bars[bar_index].open_at()
    return resolution_clock(bars, zone_end)


def _dataset_fieldnames(feature_cols: Sequence[str]) -> list[str]:
    return [
        "symbol",
        "decided_at",
        "resolved_at",
        "split",
        "zone_start",
        "zone_end",
        "pattern",
        "leg_out_mode",
        "p_accept",
        "entry",
        "stop",
        "target",
        "outcome_label",
        "y_bounce",
        "behavior",
        "path_notes",
        "source",
        *feature_cols,
    ]


def _upsert_dataset_row(path: Path, row: dict, feature_cols: Sequence[str]) -> bool:
    """Insert or replace the row with the same symbol + decided_at."""
    fieldnames = _dataset_fieldnames(feature_cols)
    existing: list[dict] = []
    updated = False

    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for old in reader:
                same = (
                    old.get("symbol", "").upper() == row["symbol"]
                    and old.get("decided_at") == row["decided_at"]
                )
                if same:
                    existing.append({key: row.get(key, "") for key in fieldnames})
                    updated = True
                else:
                    cleaned = {key: old.get(key, MISSING) for key in fieldnames}
                    existing.append(cleaned)

    if not updated:
        existing.append({key: row.get(key, "") for key in fieldnames})

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in existing:
            writer.writerow(item)
    return updated


def _write_dataset_meta(path: Path, feature_cols: Sequence[str]) -> None:
    row_count = 0
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            row_count = max(sum(1 for _ in handle) - 1, 0)

    meta = {
        "dataset_path": str(path),
        "feature_names": list(feature_cols),
        "feature_width": len(feature_cols),
        "row_count": row_count,
        "min_company_years": 3,
        "early_sessions": EARLY_LAST_SESSION,
        "entry_on_session": ENTRY_ON_SESSION,
        "outcome_labels": [
            LABEL_WIN,
            LABEL_LOSS,
            LABEL_PREMATURE,
            LABEL_NOTHING,
            LABEL_NO_FILL,
            LABEL_UNRESOLVED,
            LABEL_BAD_ENTRY,
        ],
        "manual_path_bars": MANUAL_PATH_BARS,
        "manual_path_note": (
            "After day 6 the limit stays armed up to manual_path_bars. "
            "It does not use Plan 1's 40-bar expiry."
        ),
        "includes": [
            "zone geometry features (leg-in / UOC / leg-out / SUPER 3-leg-out)",
            "footprint summaries on UOC and leg-out",
            "daily / weekly / monthly context at the decision clock",
            "HTF truncated windows (daily 20 / weekly 12 / monthly 12)",
            "memory placeholders (empty until neighbor history is wired)",
            "manual entry / stop / target",
            "automatic outcome_label from the path",
        ],
        "y_bounce": "1 only for win (target before stop after day-6 arm); else 0",
    }
    DATASET_META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def labelable_zone_to_dict(zone: LabelableZone) -> dict:
    return {
        "symbol": zone.symbol,
        "zone_start": zone.zone_start,
        "zone_end": zone.zone_end,
        "pattern": zone.pattern,
        "leg_out_mode": zone.leg_out_mode,
        "decided_at": zone.decided_at,
        "p_accept": zone.p_accept,
        "suggested_entry": zone.suggested_entry,
        "suggested_stop": zone.suggested_stop,
        "suggested_target": zone.suggested_target,
        "uoc_low": zone.uoc_low,
        "uoc_high": zone.uoc_high,
    }


def saved_row_to_dict(row: SavedRow) -> dict:
    return {
        "symbol": row.symbol,
        "decided_at": row.decided_at,
        "outcome_label": row.outcome_label,
        "y_bounce": row.y_bounce,
        "behavior": row.behavior,
        "entry": row.entry,
        "stop": row.stop,
        "target": row.target,
        "path": row.path,
        "updated": row.updated,
    }
