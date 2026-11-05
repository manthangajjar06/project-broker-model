"""Reliable sequential orchestration for independently configured symbol scans.

The module contains no NIFTY-list download, output formatting, or browser URL
resolution. Its only responsibility is to make sure a failure for one symbol
is recorded and never prevents the remaining configured symbols from running.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Final

import pandas as pd

from scan_fresh_zones import ScanConfiguration, SymbolScanResult, scan_symbol


LOG = logging.getLogger("fresh_zone_batch_scan")

SymbolScanner = Callable[[ScanConfiguration], Awaitable[SymbolScanResult]]


@dataclass(frozen=True)
class SymbolScanFailure:
    """The safely serializable failure information for one configured symbol."""

    symbol: str
    error_type: str
    message: str


@dataclass(frozen=True)
class BatchScanResult:
    """All successful scans and recoverable per-symbol failures from one run."""

    started_at: pd.Timestamp
    completed_at: pd.Timestamp
    successful_scans: tuple[SymbolScanResult, ...]
    failures: tuple[SymbolScanFailure, ...]

    @property
    def scanned_symbol_count(self) -> int:
        return len(self.successful_scans) + len(self.failures)


async def scan_configurations(
    configurations: Iterable[ScanConfiguration],
    *,
    scanner: SymbolScanner = scan_symbol,
) -> BatchScanResult:
    """Scan configurations sequentially, retaining failures and continuing.

    Sequential execution is intentional: every scan talks to the same logged-in
    Kite browser profile, and one chart's history loading should complete before
    the next chart changes. The caller provides complete configurations so this
    module remains independent of Kite's instrument-ID lookup details.
    """

    started_at = pd.Timestamp.now(tz="Asia/Kolkata")
    successful_scans: list[SymbolScanResult] = []
    failures: list[SymbolScanFailure] = []

    for position, configuration in enumerate(configurations, start=1):
        try:
            result = await scanner(configuration)
        except Exception as error:  # Per-symbol isolation is this module's purpose.
            failure = SymbolScanFailure(
                symbol=configuration.symbol,
                error_type=type(error).__name__,
                message=str(error),
            )
            failures.append(failure)
            LOG.exception(
                "Symbol %s at batch position %d failed; continuing with the next symbol.",
                configuration.symbol,
                position,
            )
            continue

        if result.symbol != configuration.symbol:
            failure = SymbolScanFailure(
                symbol=configuration.symbol,
                error_type="SymbolMismatchError",
                message=(
                    "The symbol scan returned "
                    f"{result.symbol!r}, expected {configuration.symbol!r}."
                ),
            )
            failures.append(failure)
            LOG.error("%s; continuing with the next symbol.", failure.message)
            continue

        successful_scans.append(result)
        LOG.info(
            "Completed symbol %s at batch position %d; found %d fresh zones.",
            configuration.symbol,
            position,
            len(result.zones),
        )

    return BatchScanResult(
        started_at=started_at,
        completed_at=pd.Timestamp.now(tz="Asia/Kolkata"),
        successful_scans=tuple(successful_scans),
        failures=tuple(failures),
    )
