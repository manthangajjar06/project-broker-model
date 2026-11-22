"""Step 1. Load one 2-hour CSV from RL/data.

The column set is the one in §2 of the implementation plan. A blank early
indicator cell stays blank. It is not filled with zero. The footprint cell
is split into price, buy, and sell. The raw footprint string is not kept.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


COLUMNS = (
    "interval",
    "date",
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "upper_wick_pct",
    "lower_wick_pct",
    "body_pct",
    "tr",
    "atr_14",
    "datr_14",
    "avg_volume_14d",
    "ema_20",
    "ema_50",
    "buy_volume",
    "sell_volume",
    "delta",
    "footprint",
)

# Warmup cells written blank by the history builder. A blank stays None.
BLANKABLE = (
    "atr_14",
    "datr_14",
    "avg_volume_14d",
    "ema_20",
    "ema_50",
)

REQUIRED_NUMBERS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "upper_wick_pct",
    "lower_wick_pct",
    "body_pct",
    "tr",
    "buy_volume",
    "sell_volume",
    "delta",
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class LoadError(ValueError):
    """The 2-hour file does not match the column contract."""


@dataclass(frozen=True)
class FootprintLevel:
    price: float
    buy: float
    sell: float


@dataclass(frozen=True)
class Bar:
    interval: str
    date: str
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    upper_wick_pct: float
    lower_wick_pct: float
    body_pct: float
    tr: float
    atr_14: float | None
    datr_14: float | None
    avg_volume_14d: float | None
    ema_20: float | None
    ema_50: float | None
    buy_volume: float
    sell_volume: float
    delta: float
    footprint: tuple[FootprintLevel, ...]

    def open_at(self) -> datetime:
        """The timestamp on the row is the candle open."""
        return datetime.strptime(f"{self.date} {self.time}", "%Y-%m-%d %H:%M:%S")


def csv_path(symbol: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / f"NSE_{symbol}_2hour.csv"


def parse_footprint(text: str) -> tuple[FootprintLevel, ...]:
    """Split `price=buy/sell` levels separated by `;`.

    An empty cell is no levels. A missing side on a level is zero, matching
    the chart parser. That zero belongs to the level. It is not a fill for
    a blank indicator cell.
    """
    raw = text.strip()
    if not raw:
        return ()
    levels = []
    for part in raw.split(";"):
        piece = part.strip()
        if not piece:
            continue
        price_text, separator, sides = piece.partition("=")
        if not separator:
            continue
        buy_text, _, sell_text = sides.partition("/")
        price = _finite(price_text)
        if price is None:
            continue
        levels.append(FootprintLevel(price, _side(buy_text), _side(sell_text)))
    return tuple(levels)


def load_bars(path: Path) -> list[Bar]:
    """Read one 2-hour file in the order the rows are stored."""
    path = Path(path)
    bars: list[Bar] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as error:
            raise LoadError(f"{path.name} is empty") from error
        names = tuple(cell.strip() for cell in header)
        if names != COLUMNS:
            raise LoadError(f"{path.name} columns are {names}, the plan requires {COLUMNS}")
        for line_number, cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in cells):
                continue
            where = f"{path.name} line {line_number}"
            if len(cells) != len(COLUMNS):
                raise LoadError(f"{where} has {len(cells)} columns, expected {len(COLUMNS)}")
            raw = {name: cells[index] for index, name in enumerate(COLUMNS)}
            bars.append(_bar_from_row(raw, where))
    return bars


def _bar_from_row(raw: dict[str, str], where: str) -> Bar:
    interval = _text(raw["interval"], "interval", where)
    date = _text(raw["date"], "date", where)
    clock = _text(raw["time"], "time", where)
    try:
        datetime.strptime(date, "%Y-%m-%d")
        datetime.strptime(clock, "%H:%M:%S")
    except ValueError as error:
        raise LoadError(f"{where} has a date or time that is not a candle open") from error

    numbers = {name: _required_number(raw[name], name, where) for name in REQUIRED_NUMBERS}
    blanks = {name: _blankable_number(raw[name], name, where) for name in BLANKABLE}
    return Bar(
        interval=interval,
        date=date,
        time=clock,
        open=numbers["open"],
        high=numbers["high"],
        low=numbers["low"],
        close=numbers["close"],
        volume=numbers["volume"],
        upper_wick_pct=numbers["upper_wick_pct"],
        lower_wick_pct=numbers["lower_wick_pct"],
        body_pct=numbers["body_pct"],
        tr=numbers["tr"],
        atr_14=blanks["atr_14"],
        datr_14=blanks["datr_14"],
        avg_volume_14d=blanks["avg_volume_14d"],
        ema_20=blanks["ema_20"],
        ema_50=blanks["ema_50"],
        buy_volume=numbers["buy_volume"],
        sell_volume=numbers["sell_volume"],
        delta=numbers["delta"],
        footprint=parse_footprint(raw["footprint"]),
    )


def _text(value: str, column: str, where: str) -> str:
    text = value.strip()
    if not text:
        raise LoadError(f"{where}: {column} is empty")
    return text


def _required_number(value: str, column: str, where: str) -> float:
    text = value.strip()
    if text == "":
        raise LoadError(f"{where}: {column} is empty")
    number = _finite(text)
    if number is None:
        raise LoadError(f"{where}: {column} is not a number")
    return number


def _blankable_number(value: str, column: str, where: str) -> float | None:
    text = value.strip()
    if text == "":
        return None
    number = _finite(text)
    if number is None:
        raise LoadError(f"{where}: {column} is not a number")
    return number


def _side(value: str) -> float:
    number = _finite(value)
    return 0.0 if number is None else number


def _finite(value: str) -> float | None:
    try:
        number = float(value.strip())
    except ValueError:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number
