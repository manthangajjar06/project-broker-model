"""Download and validate the official NIFTY 100 constituent list.

This module deliberately has no Playwright or scanner dependency.  Keeping the
constituent-list boundary separate makes it possible to validate the exact set
of symbols before any browser automation starts.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Final
from urllib.error import URLError
from urllib.request import Request, urlopen


NIFTY_100_CONSTITUENTS_URL: Final = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
EXPECTED_CONSTITUENT_COUNT: Final = 100
DOWNLOAD_TIMEOUT_SECONDS: Final = 30


class ConstituentListError(RuntimeError):
    """Raised when the official constituent list cannot be safely used."""


@dataclass(frozen=True)
class Nifty100Constituents:
    """A validated snapshot of the official NIFTY 100 constituent symbols."""

    source_url: str
    symbols: tuple[str, ...]


def download_constituents_csv(url: str = NIFTY_100_CONSTITUENTS_URL) -> bytes:
    """Download the official CSV with a clear timeout and useful error message."""

    request = Request(
        url,
        headers={
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
            "User-Agent": "nifty100-zone-scanner/1.0",
        },
    )
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (OSError, URLError) as error:
        raise ConstituentListError(f"Could not download the NIFTY 100 constituent CSV: {error}") from error

    if not payload:
        raise ConstituentListError("The NIFTY 100 constituent CSV was empty.")
    return payload


def parse_constituent_symbols(csv_bytes: bytes) -> tuple[str, ...]:
    """Return exactly 100 unique, non-empty symbols from an official CSV payload.

    The official file is expected to include a ``Symbol`` column.  The column
    name comparison is case-insensitive and handles a UTF-8 byte-order mark,
    but every other structural issue fails fast so that an HTML error page or
    changed source format is never mistaken for a valid stock list.
    """

    try:
        csv_text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConstituentListError("The NIFTY 100 constituent CSV was not valid UTF-8 text.") from error

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ConstituentListError("The NIFTY 100 constituent CSV did not contain a header row.")

    normalized_headers = {
        header.strip().casefold(): header
        for header in reader.fieldnames
        if header and header.strip()
    }
    symbol_header = normalized_headers.get("symbol")
    if symbol_header is None:
        available = ", ".join(reader.fieldnames)
        raise ConstituentListError(f"The NIFTY 100 constituent CSV has no Symbol column. Headers: {available}")

    symbols: list[str] = []
    seen_symbols: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        raw_symbol = row.get(symbol_header)
        symbol = raw_symbol.strip() if raw_symbol else ""
        if not symbol:
            raise ConstituentListError(f"The NIFTY 100 constituent CSV has an empty Symbol at row {row_number}.")
        if symbol in seen_symbols:
            raise ConstituentListError(f"The NIFTY 100 constituent CSV contains duplicate symbol {symbol!r}.")
        seen_symbols.add(symbol)
        symbols.append(symbol)

    if len(symbols) != EXPECTED_CONSTITUENT_COUNT:
        raise ConstituentListError(
            "Expected exactly "
            f"{EXPECTED_CONSTITUENT_COUNT} NIFTY 100 symbols, but found {len(symbols)}."
        )
    return tuple(symbols)


def load_nifty100_constituents(url: str = NIFTY_100_CONSTITUENTS_URL) -> Nifty100Constituents:
    """Download, validate, and return the official NIFTY 100 symbols."""

    return Nifty100Constituents(source_url=url, symbols=parse_constituent_symbols(download_constituents_csv(url)))
