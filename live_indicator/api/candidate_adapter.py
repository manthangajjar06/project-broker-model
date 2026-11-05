"""Convert live chart candles into rows consumable by feature_engineering."""

import json

import pandas as pd

import detector


REQUIRED_PRICE_FIELDS = ("open", "high", "low", "close")


def _to_exchange_timestamp(value):
    """Return a timezone-naive Asia/Kolkata timestamp, matching training data."""
    if isinstance(value, (int, float)):
        unit = "ms" if value > 10_000_000_000 else "s"
        return pd.to_datetime(value, unit=unit, utc=True).tz_convert("Asia/Kolkata").tz_localize(None)
    timestamp = pd.to_datetime(value)
    if timestamp.tzinfo is None:
        return timestamp
    return timestamp.tz_convert("Asia/Kolkata").tz_localize(None)


def candles_to_dataframe(candles: list[dict]) -> pd.DataFrame:
    """Validate chart candles and return the exact OHLCV dataframe rules expect."""
    rows = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, dict):
            raise ValueError(f"Candle {index} must be an object.")
        timestamp = candle.get("timestamp", candle.get("timeMs", candle.get("time")))
        if timestamp is None or any(field not in candle for field in REQUIRED_PRICE_FIELDS):
            raise ValueError(f"Candle {index} is missing timestamp or OHLC values.")
        rows.append({
            "timestamp": _to_exchange_timestamp(timestamp),
            "open": candle["open"], "high": candle["high"],
            "low": candle["low"], "close": candle["close"],
            "volume": candle.get("volume", 0),
        })

    dataframe = pd.DataFrame(rows)
    for field in REQUIRED_PRICE_FIELDS + ("volume",):
        dataframe[field] = pd.to_numeric(dataframe[field], errors="raise")
    dataframe = dataframe.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if len(dataframe) < 3:
        raise ValueError("At least three valid candles are required.")
    return dataframe


def _serialize_zone(zone: pd.DataFrame) -> str:
    serializable = zone.copy()
    serializable["timestamp"] = serializable["timestamp"].astype(str)
    return json.dumps(serializable.to_dict(orient="records"))


def build_candidate_rows(candles: list[dict]) -> pd.DataFrame:
    """Run unchanged rules and build the raw schema used to train the model."""
    dataframe = candles_to_dataframe(candles)
    tr, atr = detector.compute_tr_atr(dataframe)
    rows = []

    for candidate in detector.run_detection(dataframe):
        start = candidate["start_index"]
        end = candidate["end_index"]
        metrics = candidate["details"]["metrics"]
        zone = dataframe.iloc[start:end + 1]
        row = {
            "pattern_type": candidate["pattern_type"],
            "leg_out_mode": candidate["leg_out_mode"],
            "rally_candle_count": metrics["rally_candle_count"],
            "start_timestamp": dataframe.iloc[start]["timestamp"].isoformat(),
            "end_timestamp": dataframe.iloc[end]["timestamp"].isoformat(),
            "start_index": start,
            "end_index": end,
            "leg_in_body": metrics["leg_in_body"],
            "boring_body": metrics["boring_body"],
            "boring_ratio_pct": metrics["boring_ratio_pct"],
            "boring_color": metrics["boring_color"],
            "has_gap": metrics["has_gap"],
            "gap_size": metrics["gap_size"],
            "adjusted_leg_out_body": metrics["adjusted_leg_out_body"],
            "penetration_pct": metrics["penetration_pct"],
            "tr_at_start": tr[start], "atr_at_start": atr[start],
            "tr_atr_ratio_at_start": tr[start] / atr[start] if atr[start] else None,
            "tr_at_end": tr[end], "atr_at_end": atr[end],
            "tr_atr_ratio_at_end": tr[end] / atr[end] if atr[end] else None,
            "ohlcv_json": _serialize_zone(zone),
        }
        row.update(detector.compute_zone_features(dataframe, start, end))
        rows.append(row)

    return pd.DataFrame(rows)

