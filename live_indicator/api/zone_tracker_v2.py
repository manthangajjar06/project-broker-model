"""Corrected, isolated demand-zone entry and lifecycle logic."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

EPSILON = 1e-9


@dataclass(frozen=True)
class EntryDecision:
    base_entry: float
    final_entry: float | None
    entry_kind: str
    buffer_applied: bool
    rule: str


def _lower_wick(candle: pd.Series) -> bool:
    return float(candle["low"]) < min(float(candle["open"]), float(candle["close"])) - EPSILON


def _upper_wick(candle: pd.Series) -> bool:
    return float(candle["high"]) > max(float(candle["open"]), float(candle["close"])) + EPSILON


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return max(a_low, b_low) <= min(a_high, b_high) + EPSILON


def calculate_entry(uoc: pd.Series, leg_out: pd.Series, datr: float | None = None) -> EntryDecision:
    """Return the entry decision using the agreed five rules.

    Rule 1 is explicit: no lower wick on leg-out means entry = leg-out OPEN,
    with no DATR buffer. It remains higher priority than Rule 5.
    """
    leg_open, leg_close = float(leg_out["open"]), float(leg_out["close"])
    uoc_low, uoc_high = float(uoc["low"]), float(uoc["high"])
    if not _lower_wick(leg_out):
        return EntryDecision(leg_open, leg_open, "leg_out_open", False, "rule_1_no_leg_out_lower_wick")

    if not _overlap(min(leg_open, leg_close), max(leg_open, leg_close), uoc_low, uoc_high):
        return EntryDecision(uoc_high, uoc_high, "uoc_wick_to_wick", False, "rule_4_leg_out_body_not_touching_uoc")

    if not _upper_wick(uoc):
        return EntryDecision(leg_open, leg_open, "leg_out_open", False, "rule_5_no_uoc_upper_wick")

    red_uoc = float(uoc["close"]) < float(uoc["open"])
    base = float(uoc["open"]) if red_uoc else float(uoc["close"])
    final = base + (0.10 * float(datr)) if datr is not None else None
    return EntryDecision(base, final, "red_uoc_open" if red_uoc else "green_uoc_close", True, "rule_2_or_3_with_10pct_datr_buffer")


def _status(dataframe: pd.DataFrame, uoc: pd.Series, end: int) -> tuple[str, str | None]:
    low, high = float(uoc["low"]), float(uoc["high"])
    first_touch = None
    touched = False
    for _, candle in dataframe.iloc[end + 1:].iterrows():
        if _overlap(float(candle["low"]), float(candle["high"]), low, high):
            touched = True
            first_touch = first_touch or pd.Timestamp(candle["timestamp"]).isoformat()
        if touched and float(candle["close"]) < low - EPSILON:
            return "invalidated", first_touch
    return ("worked" if touched else "fresh"), first_touch


def build_zone_records(dataframe: pd.DataFrame, candidates: list[dict[str, Any]], symbol: str, datr: float | None = None) -> list[dict[str, Any]]:
    result = []
    for candidate in candidates:
        start, end = candidate["start_index"], candidate["end_index"]
        uoc, leg_out = dataframe.iloc[start + 1], dataframe.iloc[start + 2]
        status, draw_until = _status(dataframe, uoc, end)
        result.append({
            "zone_id": f"{symbol}:{candidate['pattern_type']}:{pd.Timestamp(uoc['timestamp']).isoformat()}",
            "symbol": symbol, "pattern_type": candidate["pattern_type"], "leg_out_mode": candidate["leg_out_mode"],
            "formed_at": pd.Timestamp(uoc["timestamp"]).isoformat(),
            "formation_end_at": pd.Timestamp(dataframe.iloc[end]["timestamp"]).isoformat(),
            "draw_until": draw_until, "zone_low": float(uoc["low"]), "zone_high": float(uoc["high"]),
            "status": status, "entry": asdict(calculate_entry(uoc, leg_out, datr)),
        })
    return result
