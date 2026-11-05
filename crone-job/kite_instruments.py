"""Resolve NSE trading symbols to the Kite instrument tokens used in chart URLs.

A Kite chart URL looks like
    https://kite.zerodha.com/chart/web/tvc/NSE/ICICIBANK/1270529
and the trailing number is the instrument token.  Opening a chart with a wrong
or missing token leaves the page without a TradingView chart, which is why
the scanner "could not open" any symbol other than ICICIBANK (whose token was
hard-coded).  This module looks the token up from Kite's public instrument
dump instead.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

INSTRUMENTS_URL: Final = "https://api.kite.trade/instruments/NSE"
CACHE_FILE: Final = Path(__file__).resolve().parent / "nse_instruments_cache.csv"
CACHE_MAX_AGE_SECONDS: Final = 12 * 60 * 60
CHART_URL_TEMPLATE: Final = "https://kite.zerodha.com/chart/web/tvc/NSE/{symbol}/{token}"


class InstrumentLookupError(RuntimeError):
    """Raised when the instrument dump cannot be downloaded or parsed."""


@dataclass(frozen=True)
class ResolvedInstruments:
    tokens: dict[str, int]      # NIFTY symbol -> instrument token
    unresolved: tuple[str, ...]  # symbols Kite does not list as NSE equity


def _download() -> bytes:
    request = Request(INSTRUMENTS_URL, headers={"User-Agent": "nifty100-zone-scanner/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read()
    except (OSError, URLError) as error:
        raise InstrumentLookupError(f"Could not download Kite instruments: {error}") from error
    if not payload.startswith(b"instrument_token"):
        raise InstrumentLookupError("Kite instrument dump did not look like a CSV.")
    return payload


def load_instrument_csv(force_refresh: bool = False) -> str:
    fresh = CACHE_FILE.is_file() and (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_MAX_AGE_SECONDS
    if fresh and not force_refresh:
        return CACHE_FILE.read_text(encoding="utf-8")
    payload = _download()
    CACHE_FILE.write_bytes(payload)
    return payload.decode("utf-8")


def parse_equity_tokens(csv_text: str) -> dict[str, int]:
    """Map tradingsymbol -> token for plain NSE equities (instrument_type EQ)."""

    tokens: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("exchange") == "NSE" and row.get("instrument_type") == "EQ" and row.get("segment") == "NSE":
            tokens[row["tradingsymbol"].strip()] = int(row["instrument_token"])
    return tokens


def resolve_symbols(symbols: list[str] | tuple[str, ...], force_refresh: bool = False) -> ResolvedInstruments:
    available = parse_equity_tokens(load_instrument_csv(force_refresh))
    found = {s: available[s] for s in symbols if s in available}
    missing = tuple(s for s in symbols if s not in available)
    return ResolvedInstruments(tokens=found, unresolved=missing)


def chart_url(symbol: str, token: int) -> str:
    """Build the chart URL; '&' in names like M&M must be percent-encoded."""

    return CHART_URL_TEMPLATE.format(symbol=quote(symbol, safe=""), token=token)
