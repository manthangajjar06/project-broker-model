"""Feature calculations matching the LightGBM training notebook exactly."""

import json

import numpy as np
import pandas as pd


CATEGORICAL_COLUMNS = ["pattern_type", "leg_out_mode", "boring_color"]

FEATURE_COLUMNS = [
    "pattern_type", "leg_out_mode", "boring_color",
    "rally_candle_count", "boring_ratio_pct", "has_gap", "penetration_pct",
    "tr_atr_ratio_at_start", "tr_atr_ratio_at_end", "candle_count", "zone_body_pct",
    "leg_out_body_pct", "leg_out_wick_upper_pct", "leg_out_wick_lower_pct",
    "leg_out_close_position", "leg_out_volume_vs_avg", "rally_min_body_pct",
    "leg_in_wick_pct", "leg_in_close_position", "boring_wick_pct",
    "zone_range_pct", "leg_in_body_pct_of_price", "gap_size_pct",
    "adjusted_leg_out_body_pct", "leg_out_volume_share", "hour_of_day",
    "day_of_week", "atr_trend", "boring_vs_leg_in_strength", "rally_dominance",
    "leg_out_body_vs_leg_in_body",
]


def extract_features(candidate_rows: pd.DataFrame) -> pd.DataFrame:
    """Return the 31 model features for candidate rows.

    Each row must follow the schema of the original ``dataset.csv``, including
    ``start_timestamp``, ``end_timestamp`` and ``ohlcv_json``.
    """
    df = candidate_rows.copy().drop_duplicates().reset_index(drop=True)

    start_dt = pd.to_datetime(df["start_timestamp"])
    end_dt = pd.to_datetime(df["end_timestamp"])
    df["hour_of_day"] = end_dt.dt.hour
    df["day_of_week"] = end_dt.dt.dayofweek

    df["atr_trend"] = df["atr_at_end"] / df["atr_at_start"].replace(0, np.nan)
    df["zone_range_pct"] = df["zone_range"] / df["zone_open"].replace(0, np.nan)
    df["leg_in_body_pct_of_price"] = df["leg_in_body"] / df["zone_open"].replace(0, np.nan)
    df["gap_size_pct"] = df["gap_size"] / df["zone_open"].replace(0, np.nan)
    df["adjusted_leg_out_body_pct"] = df["adjusted_leg_out_body"] / df["zone_open"].replace(0, np.nan)
    df["boring_vs_leg_in_strength"] = df["boring_body"] / df["leg_in_body"].replace(0, np.nan)
    df["rally_dominance"] = df["adjusted_leg_out_body"] / (
        df["leg_in_body"] + df["boring_body"]
    ).replace(0, np.nan)
    df["leg_out_body_vs_leg_in_body"] = (
        df["adjusted_leg_out_body"] / df["leg_in_body"].replace(0, np.nan)
    )

    derived = {
        "leg_out_body_pct": [], "leg_out_wick_upper_pct": [],
        "leg_out_wick_lower_pct": [], "leg_out_close_position": [],
        "leg_out_volume_vs_avg": [], "leg_out_volume_share": [],
        "rally_min_body_pct": [], "leg_in_wick_pct": [],
        "leg_in_close_position": [], "boring_wick_pct": [],
    }

    for _, row in df.iterrows():
        candles = json.loads(row["ohlcv_json"])
        first, second, last = candles[0], candles[1], candles[-1]

        first_range = first["high"] - first["low"]
        first_body = abs(first["close"] - first["open"])
        derived["leg_in_wick_pct"].append(
            (first_range - first_body) / first_range if first_range > 0 else 0.0
        )
        derived["leg_in_close_position"].append(
            (first["close"] - first["low"]) / first_range if first_range > 0 else 0.5
        )

        second_range = second["high"] - second["low"]
        second_body = abs(second["close"] - second["open"])
        derived["boring_wick_pct"].append(
            (second_range - second_body) / second_range if second_range > 0 else 0.0
        )

        rally_body_pcts = [
            abs(candle["close"] - candle["open"]) / (candle["high"] - candle["low"])
            if candle["high"] - candle["low"] > 0 else 0.0
            for candle in candles[2:]
        ]
        derived["rally_min_body_pct"].append(min(rally_body_pcts) if rally_body_pcts else 0.0)

        last_range = last["high"] - last["low"]
        last_body = abs(last["close"] - last["open"])
        if last_range > 0:
            derived["leg_out_body_pct"].append(last_body / last_range)
            derived["leg_out_wick_upper_pct"].append(
                (last["high"] - max(last["open"], last["close"])) / last_range
            )
            derived["leg_out_wick_lower_pct"].append(
                (min(last["open"], last["close"]) - last["low"]) / last_range
            )
            derived["leg_out_close_position"].append((last["close"] - last["low"]) / last_range)
        else:
            derived["leg_out_body_pct"].append(0.0)
            derived["leg_out_wick_upper_pct"].append(0.0)
            derived["leg_out_wick_lower_pct"].append(0.0)
            derived["leg_out_close_position"].append(0.5)

        average_volume = row["average_volume"]
        total_volume = row["total_volume"]
        derived["leg_out_volume_vs_avg"].append(
            last["volume"] / average_volume if average_volume > 0 else 1.0
        )
        derived["leg_out_volume_share"].append(
            last["volume"] / total_volume if total_volume > 0 else 1.0 / len(candles)
        )

    for column, values in derived.items():
        df[column] = values
    for column in CATEGORICAL_COLUMNS:
        df[column] = df[column].astype("category")

    return df[FEATURE_COLUMNS].copy()
