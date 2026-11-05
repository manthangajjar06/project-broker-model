"""
detector.py
===========

This module is responsible for:
  1. Loading and validating OHLCV data uploaded by the user.
  2. Running the pattern detection rules defined in DRBR.py against that
     data, and sanity-checking whatever DRBR.py returns.
  3. Computing generic descriptive features for a candidate pattern zone,
     so those features can be saved into dataset.csv when the user
     accepts or rejects a zone.

This file contains no trading rules itself. All pattern-specific logic
lives in DRBR.py. This file only handles data loading, orchestration, and
generic feature calculations that apply to any zone regardless of its
type.
"""

import pandas as pd

import DRBR


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def load_ohlcv_csv(filepath):
    """
    Load an OHLCV CSV file from disk into a validated, sorted pandas
    DataFrame.

    The CSV file must contain the following columns (case-insensitive,
    any column order): timestamp, open, high, low, close, volume.

    Parameters
    ----------
    filepath : str
        Path to the CSV file on disk.

    Returns
    -------
    pandas.DataFrame
        A DataFrame with columns: timestamp, open, high, low, close,
        volume. The "timestamp" column is converted to pandas datetime
        objects. The DataFrame is sorted by timestamp ascending and has a
        fresh integer index starting at 0.

    Raises
    ------
    ValueError
        If any required column is missing, or if the file cannot be
        parsed as OHLCV data.
    """
    try:
        raw_dataframe = pd.read_csv(filepath)
    except Exception as read_error:
        raise ValueError(f"Could not read CSV file: {read_error}")

    # Normalize column names to lowercase, and strip whitespace, so the
    # user's CSV can use "Open", " OPEN ", "open", etc. without breaking.
    raw_dataframe.columns = [str(column).strip().lower() for column in raw_dataframe.columns]

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in raw_dataframe.columns]
    if len(missing_columns) > 0:
        raise ValueError(
            "The uploaded CSV is missing required column(s): "
            + ", ".join(missing_columns)
            + ". Required columns are: "
            + ", ".join(REQUIRED_COLUMNS)
        )

    # Keep only the required columns, in a fixed, predictable order.
    clean_dataframe = raw_dataframe[REQUIRED_COLUMNS].copy()

    # Convert the timestamp column to real datetime objects. This accepts
    # most common formats (ISO strings, "YYYY-MM-DD HH:MM:SS", etc.). If
    # that fails, fall back to treating the column as unix seconds.
    try:
        clean_dataframe["timestamp"] = pd.to_datetime(clean_dataframe["timestamp"])
    except Exception:
        try:
            clean_dataframe["timestamp"] = pd.to_datetime(clean_dataframe["timestamp"], unit="s")
        except Exception as timestamp_error:
            raise ValueError(f"Could not parse the 'timestamp' column: {timestamp_error}")

    # Make sure the numeric columns are actually numeric. Any row that
    # fails to convert becomes NaN, and we drop those rows so bad data
    # does not silently corrupt the chart or the dataset.
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        clean_dataframe[column] = pd.to_numeric(clean_dataframe[column], errors="coerce")

    rows_before_dropping = len(clean_dataframe)
    clean_dataframe = clean_dataframe.dropna(subset=numeric_columns)
    rows_after_dropping = len(clean_dataframe)
    if rows_after_dropping < rows_before_dropping:
        dropped_count = rows_before_dropping - rows_after_dropping
        print(f"Warning: dropped {dropped_count} row(s) with invalid numeric OHLCV values.")

    if rows_after_dropping == 0:
        raise ValueError("No valid OHLCV rows remained after cleaning the uploaded CSV.")

    clean_dataframe = clean_dataframe.sort_values("timestamp")
    clean_dataframe = clean_dataframe.reset_index(drop=True)

    return clean_dataframe


# ---------------------------------------------------------------------------
# Technical Indicators: TR & ATR (Pine Script ta.tr / ta.atr conversion)
# ---------------------------------------------------------------------------

def compute_tr_atr(dataframe, length=14):
    """
    Calculate True Range (TR) and Average True Range (ATR) matching Pine Script:
      currentTR = ta.tr(true)
      currentATR = ta.atr(atrLength)
      
    Pine Script uses Wilder's RMA (Running Moving Average) for ta.atr.
    """
    n = len(dataframe)
    if n == 0:
        return [], []

    high = dataframe["high"].values
    low = dataframe["low"].values
    close = dataframe["close"].values

    tr = [0.0] * n
    tr[0] = float(high[0] - low[0])

    for i in range(1, n):
        prev_close = float(close[i - 1])
        h_l = float(high[i] - low[i])
        h_pc = abs(float(high[i]) - prev_close)
        l_pc = abs(float(low[i]) - prev_close)
        tr[i] = max(h_l, h_pc, l_pc)

    atr = [0.0] * n
    if n >= length:
        # Back-fill the warm-up period first (partial rolling average)
        for i in range(length - 1):
            atr[i] = sum(tr[: i + 1]) / (i + 1)

        # Seed the first full-window ATR with a simple average
        atr[length - 1] = sum(tr[:length]) / length

        # Wilder's RMA smoothing for all subsequent candles
        for i in range(length, n):
            atr[i] = (atr[i - 1] * (length - 1) + tr[i]) / length
    else:
        for i in range(n):
            atr[i] = sum(tr[: i + 1]) / (i + 1)

    return tr, atr


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def run_detection(dataframe):
    """
    Run the pattern detection rules from DRBR.py against the given OHLCV
    DataFrame, and validate the results before handing them back.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        OHLCV DataFrame, as returned by load_ohlcv_csv.

    Returns
    -------
    list of dict
        A list of candidate pattern zones. Each dictionary is guaranteed
        to have valid "pattern_type", "start_index", and "end_index"
        values. Any malformed candidate returned by DRBR.py is skipped
        (with a warning printed to the console) rather than crashing the
        application.
    """
    try:
        raw_candidates = DRBR.detect_patterns(dataframe)
    except Exception as detection_error:
        raise ValueError(f"DRBR.detect_patterns raised an error: {detection_error}")

    if raw_candidates is None:
        return []

    valid_candidates = []
    max_index = len(dataframe) - 1

    for candidate in raw_candidates:
        if not isinstance(candidate, dict):
            print("Warning: skipping a candidate that is not a dictionary.")
            continue

        required_keys = ["pattern_type", "start_index", "end_index"]
        missing_keys = [key for key in required_keys if key not in candidate]
        if len(missing_keys) > 0:
            print(f"Warning: skipping a candidate missing key(s): {missing_keys}")
            continue

        start_index = candidate["start_index"]
        end_index = candidate["end_index"]

        if not isinstance(start_index, int) or not isinstance(end_index, int):
            print("Warning: skipping a candidate with non-integer indices.")
            continue

        if start_index < 0 or end_index > max_index or start_index > end_index:
            print(f"Warning: skipping a candidate with out-of-range indices ({start_index}, {end_index}).")
            continue

        if candidate["pattern_type"] not in ("DBR", "RBR"):
            print(f"Warning: skipping a candidate with unknown pattern_type: {candidate['pattern_type']}")
            continue

        valid_candidates.append(candidate)

    return valid_candidates


# ---------------------------------------------------------------------------
# Feature computation for accepted / rejected zones
# ---------------------------------------------------------------------------

def compute_zone_features(dataframe, start_index, end_index):
    """
    Compute a set of generic descriptive features for a candidate zone,
    to be stored alongside the accept/reject label in dataset.csv.

    These features do not depend on any DRBR.py rules; they are simple,
    general-purpose measurements (range, body size, volume, etc.) that
    are useful for training an ML model later, regardless of exactly how
    the zone was detected or reviewed.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        The full OHLCV DataFrame for the uploaded chart.
    start_index : int
        Row index (inclusive) where the zone begins.
    end_index : int
        Row index (inclusive) where the zone ends.

    Returns
    -------
    dict
        A dictionary of computed feature values.
    """
    zone_candles = dataframe.loc[start_index:end_index]

    zone_high = zone_candles["high"].max()
    zone_low = zone_candles["low"].min()
    zone_range = zone_high - zone_low

    zone_open = zone_candles.iloc[0]["open"]
    zone_close = zone_candles.iloc[-1]["close"]
    zone_body = abs(zone_close - zone_open)

    if zone_range > 0:
        zone_body_pct = zone_body / zone_range
    else:
        zone_body_pct = 0.0

    total_volume = zone_candles["volume"].sum()
    average_volume = zone_candles["volume"].mean()
    candle_count = len(zone_candles)

    features = {
        "candle_count": candle_count,
        "zone_high": zone_high,
        "zone_low": zone_low,
        "zone_range": zone_range,
        "zone_open": zone_open,
        "zone_close": zone_close,
        "zone_body": zone_body,
        "zone_body_pct": zone_body_pct,
        "total_volume": total_volume,
        "average_volume": average_volume,
    }

    return features
