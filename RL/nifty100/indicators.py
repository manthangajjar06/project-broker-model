"""Candle columns for one scraped chart. Same math as indicator-scraper.js."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
COLUMNS = [
    "interval", "date", "time",
    "open", "high", "low", "close", "volume",
    "upper_wick_pct", "lower_wick_pct", "body_pct",
    "tr", "atr_14", "datr_14", "avg_volume_14d", "ema_20", "ema_50",
]


def ist_parts(timestamp: int) -> tuple[str, str]:
    millis = timestamp if timestamp > 10_000_000_000 else timestamp * 1000
    clock = datetime.fromtimestamp(millis / 1000, IST)
    return clock.strftime("%Y-%m-%d"), clock.strftime("%H:%M:%S")


def _blank(value: float | None, digits: int) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_rows(symbol: str, candles: dict[int, dict], interval: str = "2hour") -> list[dict]:
    ordered = [candles[key] for key in sorted(candles)]
    rows = []
    for candle in ordered:
        date, clock = ist_parts(int(candle["timestamp"]))
        if interval == "2hour" and clock == "00:00:00":
            continue
        rows.append({
            "date": date,
            "time": clock,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "volume": float(candle.get("volume") or 0),
        })

    true_range = []
    for index, row in enumerate(rows):
        span = row["high"] - row["low"]
        if index == 0:
            true_range.append(span)
            continue
        previous_close = rows[index - 1]["close"]
        true_range.append(max(span, abs(row["high"] - previous_close), abs(row["low"] - previous_close)))

    atr = [None] * len(rows)
    if len(rows) >= 14:
        atr[13] = sum(true_range[:14]) / 14
        for index in range(14, len(rows)):
            atr[index] = (atr[index - 1] * 13 + true_range[index]) / 14

    day_order = []
    days: dict[str, dict] = {}
    for row in rows:
        day = days.get(row["date"])
        if day is None:
            days[row["date"]] = {"high": row["high"], "low": row["low"], "close": row["close"], "volume": 0.0}
            day_order.append(row["date"])
            day = days[row["date"]]
        day["high"] = max(day["high"], row["high"])
        day["low"] = min(day["low"], row["low"])
        day["close"] = row["close"]
        day["volume"] += row["volume"]

    day_tr = []
    for index, date in enumerate(day_order):
        day = days[date]
        span = day["high"] - day["low"]
        if index == 0:
            day_tr.append(span)
            continue
        previous_close = days[day_order[index - 1]]["close"]
        day_tr.append(max(span, abs(day["high"] - previous_close), abs(day["low"] - previous_close)))

    ewm = [None] * len(day_order)
    if day_tr:
        accumulator = day_tr[0]
        for index in range(1, len(day_tr)):
            accumulator = accumulator * (13 / 14) + day_tr[index] / 14
            if index >= 13:
                ewm[index] = accumulator

    datr_by_date = {}
    average_volume_by_date = {}
    for index, date in enumerate(day_order):
        datr_by_date[date] = None if index == 0 else ewm[index - 1]
        if index < 14:
            average_volume_by_date[date] = None
        else:
            total = sum(days[day_order[pos]]["volume"] for pos in range(index - 14, index))
            average_volume_by_date[date] = total / 14

    closes = [row["close"] for row in rows]

    def ema(length: int) -> list[float | None]:
        values: list[float | None] = [None] * len(closes)
        if len(closes) < length:
            return values
        previous = sum(closes[:length]) / length
        values[length - 1] = previous
        weight = 2 / (length + 1)
        for index in range(length, len(closes)):
            previous = closes[index] * weight + previous * (1 - weight)
            values[index] = previous
        return values

    ema_20 = ema(20)
    ema_50 = ema(50)
    output = []
    for index, row in enumerate(rows):
        span = row["high"] - row["low"]
        upper = row["high"] - max(row["open"], row["close"])
        lower = min(row["open"], row["close"]) - row["low"]
        body = abs(row["close"] - row["open"])
        share = (lambda part: (part / span) * 100 if span else 0.0)
        output.append({
            "interval": interval,
            "date": row["date"],
            "time": row["time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "upper_wick_pct": share(upper),
            "lower_wick_pct": share(lower),
            "body_pct": share(body),
            "tr": true_range[index],
            "atr_14": atr[index],
            "datr_14": datr_by_date[row["date"]],
            "avg_volume_14d": average_volume_by_date[row["date"]],
            "ema_20": ema_20[index],
            "ema_50": ema_50[index],
        })
    return output


def csv_path(symbol: str, interval: str = "2hour") -> Path:
    return DATA_DIR / f"NSE_{symbol}_{interval}.csv"


def write_csv(symbol: str, candles: dict[int, dict], interval: str = "2hour") -> Path:
    rows = build_rows(symbol, candles, interval)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = csv_path(symbol, interval)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: row[key] for key in COLUMNS[:3]},
                "open": _price(row["open"]),
                "high": _price(row["high"]),
                "low": _price(row["low"]),
                "close": _price(row["close"]),
                "volume": _price(row["volume"]),
                "upper_wick_pct": _blank(row["upper_wick_pct"], 4),
                "lower_wick_pct": _blank(row["lower_wick_pct"], 4),
                "body_pct": _blank(row["body_pct"], 4),
                "tr": _blank(row["tr"], 4),
                "atr_14": _blank(row["atr_14"], 4),
                "datr_14": _blank(row["datr_14"], 4),
                "avg_volume_14d": _blank(row["avg_volume_14d"], 2),
                "ema_20": _blank(row["ema_20"], 4),
                "ema_50": _blank(row["ema_50"], 4),
            })
    return path
