"""Download the official Nifty 100 symbol list."""

from __future__ import annotations

import csv
import io
from urllib.error import URLError
from urllib.request import Request, urlopen

NIFTY_100_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
EXPECTED_COUNT = 100


class ConstituentListError(RuntimeError):
    """The official list was missing or not exactly 100 symbols."""


def download_constituents_csv(url: str = NIFTY_100_URL) -> bytes:
    # The index site stalls requests that do not look like a browser.
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read()
    except (OSError, URLError) as error:
        raise ConstituentListError(f"Could not download the Nifty 100 list: {error}") from error
    if not payload:
        raise ConstituentListError("The Nifty 100 list was empty.")
    return payload


def parse_constituent_symbols(csv_bytes: bytes) -> tuple[str, ...]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConstituentListError("The Nifty 100 list was not UTF-8 text.") from error

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ConstituentListError("The Nifty 100 list has no header row.")

    symbol_header = next((name for name in reader.fieldnames if name and name.strip().casefold() == "symbol"), None)
    if symbol_header is None:
        raise ConstituentListError(f"The Nifty 100 list has no Symbol column. Headers: {', '.join(reader.fieldnames)}")

    symbols: list[str] = []
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        symbol = (row.get(symbol_header) or "").strip()
        if not symbol:
            raise ConstituentListError(f"Empty symbol at row {row_number}.")
        if symbol in seen:
            raise ConstituentListError(f"Duplicate symbol {symbol}.")
        seen.add(symbol)
        symbols.append(symbol)

    if len(symbols) != EXPECTED_COUNT:
        raise ConstituentListError(f"Expected {EXPECTED_COUNT} symbols, found {len(symbols)}.")
    return tuple(symbols)


def load_nifty100_symbols(url: str = NIFTY_100_URL) -> tuple[str, ...]:
    return parse_constituent_symbols(download_constituents_csv(url))
