"""Build 2-hour candles from Kite 1-minute history.

The walk starts at the newest window and moves backward. It stops at the
first gap, so a symbol is not given minutes older than the chart can show.
A normal day stays on the 09:15 grid. A short or evening session is labelled
from its own first minute.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from indicators import DATA_DIR, csv_path

IST = ZoneInfo("Asia/Kolkata")
NORMAL_OPEN = 9 * 60 + 15
NORMAL_LAST = 15 * 60 + 29
SHORT_SESSION_BARS = 90
GAP_DAYS = 10
WINDOW_DAYS = 58
COLUMNS = [
    "interval", "date", "time",
    "open", "high", "low", "close", "volume",
    "upper_wick_pct", "lower_wick_pct", "body_pct",
    "tr", "atr_14", "datr_14", "avg_volume_14d", "ema_20", "ema_50",
    "buy_volume", "sell_volume", "delta", "footprint",
]


class HistoryError(RuntimeError):
    """The historical request failed for a reason other than the session token."""


class TokenRejected(HistoryError):
    """Zerodha did not accept the enctoken."""


@dataclass
class Minute:
    stamp: str
    mins: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Candle:
    date: str
    start_min: int
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    buy: float = 0.0
    sell: float = 0.0
    bins: dict[float, dict[str, float]] = field(default_factory=dict)


def today_ist(now: datetime | None = None) -> str:
    clock = now.astimezone(IST) if now else datetime.now(IST)
    return clock.date().isoformat()


def now_minutes_ist(now: datetime | None = None) -> int:
    clock = now.astimezone(IST) if now else datetime.now(IST)
    return clock.hour * 60 + clock.minute


def add_days(iso: str, days: int) -> str:
    year, month, day = (int(part) for part in iso.split("-"))
    return (date(year, month, day) + timedelta(days=days)).isoformat()


def day_span(older: str, newer: str) -> int:
    return (date.fromisoformat(newer) - date.fromisoformat(older)).days


def clock_label(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}:00"


def normalize_token(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    if not text or " " in text and not text.lower().startswith("enctoken "):
        return ""
    if text.lower().startswith("enctoken "):
        secret = text.split(" ", 1)[1].strip().strip('"').strip("'")
        return f"enctoken {secret}" if secret and " " not in secret else ""
    return f"enctoken {text}"


def has_footprint(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open(encoding="utf-8") as handle:
        header = handle.readline()
    return "footprint" in {name.strip() for name in header.split(",")}


def historical_url(instrument: str, user_id: str, start: str, end: str) -> str:
    query = {"oi": "1", "from": start, "to": end}
    if user_id:
        query["user_id"] = user_id
    return f"https://kite.zerodha.com/oms/instruments/historical/{instrument}/minute?{urlencode(query)}"


def decode_kite_body(text: str) -> dict:
    """Turn a Kite response into JSON. A web page is reported in one sentence."""

    stripped = text.lstrip()
    if stripped.startswith("<") or stripped.lower().startswith("<!doctype"):
        return {"status": "error", "message": "Kite returned a web page instead of data."}
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "message": "Kite returned an unreadable response."}
    if isinstance(body, dict):
        return body
    return {"status": "error", "message": "Kite returned an unexpected response."}


def kite_get(url: str, authorization: str) -> tuple[int, dict]:
    request = Request(
        url,
        headers={
            "accept": "application/json, */*",
            "authorization": authorization,
            "user-agent": "Mozilla/5.0",
            "referer": "https://kite.zerodha.com/",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, decode_kite_body(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, decode_kite_body(error.read().decode("utf-8", "replace"))
    except URLError as error:
        raise HistoryError(f"Could not reach Kite: {error.reason}") from error


def confirm_enctoken(
    authorization: str,
    get: Callable[[str, str], tuple[int, dict]] = kite_get,
    instrument: str = "1270529",
    user_id: str = "",
    end: str | None = None,
) -> str:
    """Check the enctoken with one historical request. Raise when it is missing or rejected."""

    if not authorization.startswith("enctoken ") or authorization == "enctoken ":
        raise TokenRejected("Zerodha enctoken is missing.")
    finish = end or today_ist()
    status, body = get(historical_url(instrument, user_id, add_days(finish, -1), finish), authorization)
    if status != 200 or body.get("status") != "success":
        message = body.get("message") if isinstance(body, dict) else ""
        if "Basic Authorization" in str(message):
            message = "Zerodha rejected the enctoken. Log in to Kite again, then run this once more."
        raise TokenRejected(message or f"Zerodha rejected the enctoken ({status}).")
    return user_id


def _keep_minute(store: dict[str, list[Minute]], bar: list) -> None:
    stamp = str(bar[0])
    parts = stamp.split("T", 1)
    if len(parts) != 2 or not (bar[5] > 0):
        return
    hour = int(parts[1][0:2])
    minute = int(parts[1][3:5])
    mins = hour * 60 + minute
    if mins < NORMAL_OPEN:
        return
    store.setdefault(parts[0], []).append(Minute(
        stamp, mins, float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4]), float(bar[5]),
    ))


def load_minutes(
    get: Callable[[str, str], tuple[int, dict]],
    authorization: str,
    instrument: str,
    user_id: str,
    end: str,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict[str, list[Minute]]:
    store: dict[str, list[Minute]] = {}
    oldest: str | None = None
    to = end
    while to >= "2000-01-01":
        start = add_days(to, -WINDOW_DAYS)
        status, body = _request(get, historical_url(instrument, user_id, start, to), authorization, sleep, log)
        bars = (body.get("data") or {}).get("candles") or []
        if status != 200 or body.get("status") != "success":
            if status in (401, 403):
                raise TokenRejected(body.get("message") or f"Zerodha rejected the enctoken ({status}).")
            raise HistoryError(body.get("message") or f"Kite returned {status} for {start} to {to}.")
        if not bars:
            log(f"empty {start} -> {to}, oldest real minute is {oldest}")
            break
        gap = False
        for bar in sorted(bars, key=lambda item: str(item[0]), reverse=True):
            stamp = str(bar[0])
            if not (bar[1] or bar[2] or bar[3] or bar[4]):
                continue
            if oldest is None:
                _keep_minute(store, bar)
                oldest = stamp
                continue
            if stamp >= oldest:
                continue
            if day_span(stamp[:10], oldest[:10]) > GAP_DAYS:
                log(f"gap before {oldest}, ignored {stamp}")
                gap = True
                break
            _keep_minute(store, bar)
            oldest = stamp
        log(f"{start} -> {to}: {len(bars)} minutes, oldest {oldest}, {len(store)} days")
        if gap:
            break
        to = add_days(start, -1)
        sleep(0.4)
    return store


def _request(get, url, authorization, sleep, log) -> tuple[int, dict]:
    for attempt in range(5):
        status, body = get(url, authorization)
        if status != 429:
            return status, body
        log("rate limited, waiting 3s")
        sleep(3)
    return 429, {"status": "error", "message": "rate limited"}


def build_candles(minutes_by_date: dict[str, list[Minute]]) -> tuple[list[Candle], list[dict]]:
    candles: list[Candle] = []
    odd_days: list[dict] = []
    for day in sorted(minutes_by_date):
        bars = sorted(minutes_by_date[day], key=lambda item: item.stamp)
        first = bars[0].mins
        last = bars[-1].mins
        special = first >= 15 * 60 + 30 or len(bars) <= SHORT_SESSION_BARS
        anchor = first if special else NORMAL_OPEN
        if first != NORMAL_OPEN or last != NORMAL_LAST:
            odd_days.append({
                "date": day,
                "first_minute": clock_label(first)[:5],
                "last_minute": clock_label(last)[:5],
                "bars": len(bars),
                "anchor": clock_label(anchor)[:5],
                "special": special,
            })
        grouped: dict[int, Candle] = {}
        for bar in bars:
            index = (bar.mins - anchor) // 120
            candle = grouped.get(index)
            if candle is None:
                start = anchor + index * 120
                candle = Candle(day, start, clock_label(start), bar.open, bar.high, bar.low, bar.close)
                grouped[index] = candle
            else:
                candle.high = max(candle.high, bar.high)
                candle.low = min(candle.low, bar.low)
                candle.close = bar.close
            span = bar.high - bar.low
            buy_share = (bar.close - bar.low) / span if span > 0 else 0.5
            buy = bar.volume * buy_share
            sell = bar.volume - buy
            level = int(bar.close * 4 + 1e-6) / 4
            candle.volume += bar.volume
            candle.buy += buy
            candle.sell += sell
            bin_row = candle.bins.setdefault(level, {"buy": 0.0, "sell": 0.0})
            bin_row["buy"] += buy
            bin_row["sell"] += sell
        candles.extend(grouped[index] for index in sorted(grouped))
    return candles, odd_days


def drop_partial(candles: list[Candle], end: str, now_minutes: int) -> list[Candle]:
    kept = []
    for candle in candles:
        if candle.date != end:
            kept.append(candle)
            continue
        if now_minutes >= candle.start_min + 120 or now_minutes >= 15 * 60 + 35:
            kept.append(candle)
    return kept


def _blank(value: float | None, digits: int) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _price(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def indicator_rows(candles: list[Candle]) -> list[dict]:
    true_range = []
    for index, candle in enumerate(candles):
        span = candle.high - candle.low
        if index == 0:
            true_range.append(span)
            continue
        previous = candles[index - 1].close
        true_range.append(max(span, abs(candle.high - previous), abs(candle.low - previous)))

    atr: list[float | None] = [None] * len(candles)
    if len(candles) >= 14:
        atr[13] = sum(true_range[:14]) / 14
        for index in range(14, len(candles)):
            atr[index] = (atr[index - 1] * 13 + true_range[index]) / 14

    day_order: list[str] = []
    days: dict[str, dict] = {}
    for candle in candles:
        day = days.get(candle.date)
        if day is None:
            days[candle.date] = {"high": candle.high, "low": candle.low, "close": candle.close, "volume": 0.0}
            day_order.append(candle.date)
            day = days[candle.date]
        day["high"] = max(day["high"], candle.high)
        day["low"] = min(day["low"], candle.low)
        day["close"] = candle.close
        day["volume"] += candle.volume

    day_range = []
    for index, day_name in enumerate(day_order):
        day = days[day_name]
        span = day["high"] - day["low"]
        if index == 0:
            day_range.append(span)
            continue
        previous = days[day_order[index - 1]]["close"]
        day_range.append(max(span, abs(day["high"] - previous), abs(day["low"] - previous)))

    smoothed: list[float | None] = [None] * len(day_order)
    if day_range:
        accumulator = day_range[0]
        for index in range(1, len(day_range)):
            accumulator = accumulator * (13 / 14) + day_range[index] / 14
            if index >= 13:
                smoothed[index] = accumulator

    datr: dict[str, float | None] = {}
    average_volume: dict[str, float | None] = {}
    for index, day_name in enumerate(day_order):
        datr[day_name] = None if index == 0 else smoothed[index - 1]
        if index < 14:
            average_volume[day_name] = None
        else:
            total = sum(days[day_order[pos]]["volume"] for pos in range(index - 14, index))
            average_volume[day_name] = total / 14

    closes = [candle.close for candle in candles]

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
    rows = []
    for index, candle in enumerate(candles):
        span = candle.high - candle.low
        upper = candle.high - max(candle.open, candle.close)
        lower = min(candle.open, candle.close) - candle.low
        body = abs(candle.close - candle.open)
        share = (lambda part: (part / span) * 100 if span else 0.0)
        footprint = ";".join(
            f"{level:.2f}={round(side['buy'])}/{round(side['sell'])}"
            for level, side in sorted(candle.bins.items())
        )
        rows.append({
            "interval": "2hour",
            "date": candle.date,
            "time": candle.time,
            "open": _price(candle.open),
            "high": _price(candle.high),
            "low": _price(candle.low),
            "close": _price(candle.close),
            "volume": str(round(candle.volume)),
            "upper_wick_pct": f"{share(upper):.4f}",
            "lower_wick_pct": f"{share(lower):.4f}",
            "body_pct": f"{share(body):.4f}",
            "tr": f"{true_range[index]:.4f}",
            "atr_14": _blank(atr[index], 4),
            "datr_14": _blank(datr[candle.date], 4),
            "avg_volume_14d": _blank(average_volume[candle.date], 2),
            "ema_20": _blank(ema_20[index], 4),
            "ema_50": _blank(ema_50[index], 4),
            "buy_volume": str(round(candle.buy)),
            "sell_volume": str(round(candle.sell)),
            "delta": str(round(candle.buy - candle.sell)),
            "footprint": footprint,
        })
    return rows


def write_history(symbol: str, rows: list[dict]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = csv_path(symbol, "2hour")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_symbol(
    get: Callable[[str, str], tuple[int, dict]],
    authorization: str,
    symbol: str,
    instrument: str,
    user_id: str,
    end: str,
    now_minutes: int,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> tuple[Path, list[dict]]:
    minutes = load_minutes(get, authorization, instrument, user_id, end, sleep, log)
    candles, odd_days = build_candles(minutes)
    finished = drop_partial(candles, end, now_minutes)
    if not finished:
        raise HistoryError(f"{symbol} returned no finished 2-hour candles.")
    path = write_history(symbol, indicator_rows(finished))
    return path, odd_days
