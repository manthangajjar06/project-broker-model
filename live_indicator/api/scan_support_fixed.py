"""Validated, closed-candle scan pipeline for the unified indicator."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

import DRBR
import detector
from feature_engineering import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, extract_features

EPSILON = 1e-9
MAX_CANDLES = 20_000
WARMUP_BARS = 100


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    base_entry: float
    final_entry: float
    entry_kind: str
    buffer_applied: bool
    rule: str
    warning: str | None = None


def _ist_timestamp(value: Any) -> pd.Timestamp:
    if isinstance(value, (int, float)):
        unit = "ms" if value > 10_000_000_000 else "s"
        return pd.to_datetime(value, unit=unit, utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
    stamp = pd.to_datetime(value)
    return stamp.tz_convert("Asia/Kolkata").tz_localize(None) if stamp.tzinfo else stamp


def prepare_dataframe(candles: list[dict]) -> tuple[pd.DataFrame, int]:
    if len(candles) > MAX_CANDLES:
        raise InputError(f"At most {MAX_CANDLES} candles are allowed.")
    rows = []
    for item in candles:
        if not isinstance(item, dict):
            continue
        try:
            rows.append({"timestamp": _ist_timestamp(item.get("timestamp", item.get("timeMs", item.get("time")))),
                         "open": item["open"], "high": item["high"], "low": item["low"],
                         "close": item["close"], "volume": item.get("volume", 0)})
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        raise InputError("No valid candle objects were supplied.")
    df = pd.DataFrame(rows)
    for field in ("open", "high", "low", "close", "volume"):
        df[field] = pd.to_numeric(df[field], errors="coerce")
    sane = (df["low"] > 0) & (df["volume"] >= 0) & (df["high"] >= df[["open", "close"]].max(axis=1)) & (df["low"] <= df[["open", "close"]].min(axis=1))
    dropped = int((~sane).sum())
    df = df.loc[sane].sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if len(df) < 3:
        raise InputError("Fewer than three valid OHLC candles remain.")
    if dropped > max(5, len(rows) * 0.10):
        raise InputError("Too many invalid candles were supplied.")
    return df, dropped


def _interval(df: pd.DataFrame) -> pd.Timedelta:
    same_day = df["timestamp"].diff().where(df["timestamp"].dt.date.eq(df["timestamp"].shift().dt.date)).dropna()
    diffs = same_day if not same_day.empty else df["timestamp"].diff().dropna()
    return diffs.mode().iloc[0] if not diffs.empty else pd.Timedelta(minutes=1)


def drop_forming_candle(df: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    last = df["timestamp"].iloc[-1]
    session_close = last.normalize() + pd.Timedelta(hours=15, minutes=30)
    closes_at = min(last + _interval(df), session_close)
    return df.iloc[:-1].reset_index(drop=True) if now < closes_at else df


def _super_candidates(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Add valid 3-candle SUPER rallies without removing valid SINGLE setups."""
    rows, result, n = df.to_dict("records"), [], len(df)
    for i in range(n - 4):
        one, base, three, four, five = rows[i:i + 5]
        for kind, leg_ok in (("DBR", DRBR.is_valid_red_candle(one)), ("RBR", DRBR.is_valid_green_candle(one))):
            if not leg_ok or not DRBR.is_same_day(one, base):
                continue
            leg_body = abs(one["close"] - one["open"])
            if not DRBR.is_boring_candle(base, leg_body) or three["close"] <= three["open"]:
                continue
            raw_body, raw_range = three["close"] - three["open"], three["high"] - three["low"]
            if raw_range <= 0 or raw_body < raw_range - raw_body or three["open"] < base["low"]:
                continue
            if kind == "DBR" and three["open"] > one["open"]:
                continue
            if any(c["close"] < c["open"] for c in (four, five)) or not (four["close"] > four["open"] or five["close"] > five["open"]):
                continue
            base_body = abs(base["close"] - base["open"])
            base_green = base["close"] >= base["open"]
            base_top = base["close"] if base_green else base["open"]
            gap = DRBR.compute_gap_and_overlap(base_top, base_body, three["open"])
            super_body = five["close"] - gap["effective_open"]
            super_range = max(three["high"], four["high"], five["high"]) - min(three["low"], four["low"], five["low"], gap["effective_open"])
            super_wick = super_range - super_body
            if not (super_body > super_wick and super_body > leg_body and super_body > base_body):
                continue
            common = dict(mode="SUPER (3 Candles)", start_index=i, end_index=i + 4, leg_in_body=leg_body,
                          boring_body=base_body, boring_pct=(base_body / leg_body * 100 if leg_body else 0),
                          boring_is_green=base_green, has_gap=gap["has_gap"], gap_size=gap["gap_size"],
                          penetration_pct=gap["penetration_pct"], raw_leg_out_body=raw_body,
                          adjusted_leg_out_body=super_body, rally_candle_count=3, super_rally_wick=super_wick)
            if kind == "DBR":
                result.append(DRBR._build_dbr_candidate(leg_in_open=one["open"], leg_out_open=three["open"], **common))
            else:
                result.append(DRBR._build_rbr_candidate(**common))
    return result


def detect_once(df: pd.DataFrame) -> list[dict[str, Any]]:
    candidates = detector.run_detection(df) + _super_candidates(df)
    unique = {(c["pattern_type"], c["start_index"], c["end_index"], c["leg_out_mode"]): c for c in candidates}
    return sorted(unique.values(), key=lambda c: (c["start_index"], c["end_index"], c["leg_out_mode"]))


def _iso(value: pd.Timestamp) -> str:
    return pd.Timestamp(value).tz_localize("Asia/Kolkata").isoformat()


def _daily_atr(df: pd.DataFrame, length: int = 14) -> dict[Any, float]:
    daily = df.groupby(df["timestamp"].dt.date).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    previous = daily["close"].shift()
    tr = pd.concat([daily["high"] - daily["low"], (daily["high"] - previous).abs(), (daily["low"] - previous).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False, min_periods=length).mean().shift(1).dropna().to_dict()


def _entry(uoc: pd.Series, leg_out: pd.Series, datr: float | None) -> Entry:
    leg_open, leg_close = float(leg_out["open"]), float(leg_out["close"])
    lower_wick = float(leg_out["low"]) < min(leg_open, leg_close) - EPSILON
    upper_wick = float(uoc["high"]) > max(float(uoc["open"]), float(uoc["close"])) + EPSILON
    overlap = max(min(leg_open, leg_close), float(uoc["low"])) <= min(max(leg_open, leg_close), float(uoc["high"])) + EPSILON
    if not lower_wick:
        return Entry(leg_open, leg_open, "leg_out_open", False, "rule_1_no_leg_out_lower_wick")
    if not overlap:
        price = float(uoc["high"])
        return Entry(price, price, "uoc_wick_to_wick", False, "rule_4_leg_out_body_not_touching_uoc")
    if not upper_wick:
        return Entry(leg_open, leg_open, "leg_out_open", False, "rule_5_no_uoc_upper_wick")
    red = float(uoc["close"]) < float(uoc["open"])
    base = float(uoc["open"]) if red else float(uoc["close"])
    kind = "red_uoc_open" if red else "green_uoc_close"
    if datr is None or not np.isfinite(datr) or datr <= 0:
        return Entry(base, base, kind, False, "rule_2_or_3_datr_unavailable", "datr_unavailable")
    return Entry(base, base + 0.10 * float(datr), kind, True, "rule_2_or_3_with_10pct_datr_buffer")


def build_zones(df: pd.DataFrame, candidates: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    atr_by_day, zones = _daily_atr(df), []
    last_time = _iso(df["timestamp"].iloc[-1])
    for c in candidates:
        start, end = c["start_index"], c["end_index"]
        uoc, legout = df.iloc[start + 1], df.iloc[start + 2]
        low, high = float(uoc["low"]), float(uoc["high"])
        later = df.iloc[end + 1:]
        overlap = (later["low"].to_numpy() <= high + EPSILON) & (later["high"].to_numpy() >= low - EPSILON)
        first_touch = _iso(later.iloc[int(np.argmax(overlap))]["timestamp"]) if overlap.any() else None
        status = "worked" if first_touch else "fresh"
        formed = _iso(uoc["timestamp"])
        mode = c["leg_out_mode"]
        zones.append({"zone_id": f"{symbol}:{c['pattern_type']}:{mode}:{formed}", "visual_id": f"{symbol}:{c['pattern_type']}:{formed}",
                      "symbol": symbol, "pattern_type": c["pattern_type"], "leg_out_mode": mode, "formed_at": formed,
                      "formation_end_at": _iso(df.iloc[end]["timestamp"]), "draw_until": first_touch or last_time,
                      "zone_low": low, "zone_high": high, "status": status,
                      "entry": asdict(_entry(uoc, legout, atr_by_day.get(uoc["timestamp"].date())))})
    return zones


def candidate_rows(df: pd.DataFrame, candidates: list[dict[str, Any]]) -> pd.DataFrame:
    tr, atr = detector.compute_tr_atr(df)
    rows = []
    for c in candidates:
        start, end, m = c["start_index"], c["end_index"], c["details"]["metrics"]
        zone = df.iloc[start:end + 1].copy(); zone["timestamp"] = zone["timestamp"].astype(str)
        row = {"pattern_type": c["pattern_type"], "leg_out_mode": c["leg_out_mode"], "rally_candle_count": m["rally_candle_count"],
               "start_timestamp": df.iloc[start]["timestamp"].isoformat(), "end_timestamp": df.iloc[end]["timestamp"].isoformat(),
               "start_index": start, "end_index": end, "leg_in_body": m["leg_in_body"], "boring_body": m["boring_body"],
               "boring_ratio_pct": m["boring_ratio_pct"], "boring_color": m["boring_color"], "has_gap": m["has_gap"],
               "gap_size": m["gap_size"], "adjusted_leg_out_body": m["adjusted_leg_out_body"], "penetration_pct": m["penetration_pct"],
               "tr_at_start": tr[start], "atr_at_start": atr[start], "tr_atr_ratio_at_start": tr[start] / atr[start] if atr[start] else np.nan,
               "tr_at_end": tr[end], "atr_at_end": atr[end], "tr_atr_ratio_at_end": tr[end] / atr[end] if atr[end] else np.nan,
               "ohlcv_json": json.dumps(zone.to_dict(orient="records"))}
        row.update(detector.compute_zone_features(df, start, end)); rows.append(row)
    return pd.DataFrame(rows)


def score_rows(rows: pd.DataFrame, model: Any) -> list[dict[str, Any] | None]:
    if rows.empty or model is None:
        return [None] * len(rows)
    features = extract_features(rows)
    for field in FEATURE_COLUMNS:
        if field not in CATEGORICAL_COLUMNS:
            features[field] = pd.to_numeric(features[field], errors="coerce")
    probabilities = model.predict(features)
    result = []
    for probability in probabilities:
        p = float(probability)
        label = "accepted" if p >= 0.55 else "rejected" if p <= 0.45 else "uncertain"
        result.append({"p_accept": round(p, 4), "label": label})
    return result
