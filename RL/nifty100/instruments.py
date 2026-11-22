"""Turn a Nifty 100 symbol into the Kite chart address shown in the browser."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

INSTRUMENTS_URL = "https://api.kite.trade/instruments/NSE"
CACHE_FILE = Path(__file__).resolve().parent / "nse_instruments_cache.csv"
CACHE_MAX_AGE_SECONDS = 12 * 60 * 60
CHART_URL = "https://kite.zerodha.com/markets/chart/web/tvc/NSE/{symbol}/{token}"


class InstrumentLookupError(RuntimeError):
    """Kite's public instrument list could not be downloaded or read."""


def _download() -> bytes:
    request = Request(INSTRUMENTS_URL, headers={"User-Agent": "rl-nifty100-scrape/1.0"})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read()
    except (OSError, URLError) as error:
        raise InstrumentLookupError(f"Could not download Kite instruments: {error}") from error
    if not payload.startswith(b"instrument_token"):
        raise InstrumentLookupError("Kite instrument list did not look like a CSV.")
    return payload


def load_instrument_csv(force_refresh: bool = False) -> str:
    fresh = CACHE_FILE.is_file() and (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_MAX_AGE_SECONDS
    if fresh and not force_refresh:
        return CACHE_FILE.read_text(encoding="utf-8")
    payload = _download()
    CACHE_FILE.write_bytes(payload)
    return payload.decode("utf-8")


def parse_equity_tokens(csv_text: str) -> dict[str, int]:
    """Map trading symbol to instrument token for NSE equities only."""
    tokens: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("exchange") == "NSE" and row.get("instrument_type") == "EQ" and row.get("segment") == "NSE":
            tokens[row["tradingsymbol"].strip()] = int(row["instrument_token"])
    return tokens


def chart_url(symbol: str, token: int) -> str:
    return CHART_URL.format(symbol=quote(symbol, safe=""), token=token)


def resolve_chart_urls(symbols: tuple[str, ...] | list[str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return chart URLs for the symbols Kite lists, and the names it does not."""
    tokens = parse_equity_tokens(load_instrument_csv())
    urls = {symbol: chart_url(symbol, tokens[symbol]) for symbol in symbols if symbol in tokens}
    missing = tuple(symbol for symbol in symbols if symbol not in tokens)
    return urls, missing
