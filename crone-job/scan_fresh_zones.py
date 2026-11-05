"""Scan ICICIBANK's two-hour Kite chart for untouched demand/supply zones.

This is intentionally a standalone job.  It connects to a Brave instance that
the user has already logged into, reads chart candles, and calls the existing
zone-detection functions directly.  It never starts or changes the live
indicator service, Tampermonkey script, model, or SQLite history database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


JOB_DIRECTORY = Path(__file__).resolve().parent
PROJECT_DIRECTORY = JOB_DIRECTORY.parent
API_DIRECTORY = PROJECT_DIRECTORY / "live_indicator" / "api"
OUTPUT_FILE = JOB_DIRECTORY / "zones.txt"

if str(API_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(API_DIRECTORY))

# These are the exact functions called by the existing fixed unified scanner.
from scan_support_fixed import (  # noqa: E402
    WARMUP_BARS,
    build_zones,
    candidate_rows,
    detect_once,
    drop_forming_candle,
    prepare_dataframe,
    score_rows,
)


LOG = logging.getLogger("fresh_zone_scan")


@dataclass(frozen=True)
class ScanConfiguration:
    """The chart and history settings required to scan one NSE symbol."""

    symbol: str = "NSE:ICICIBANK"
    chart_url: str = "https://kite.zerodha.com/chart/web/tvc/NSE/ICICIBANK/1270529"
    resolution: str = "120"
    history_years: int = 2
    warmup_days: int = 90
    maximum_pan_attempts: int = 240
    cdp_url: str = "http://127.0.0.1:9222"


@dataclass(frozen=True)
class SymbolScanResult:
    """Complete in-memory result of one successful symbol scan.

    This intentionally holds no batch-specific state. A later batch runner
    can call ``scan_symbol`` once per configured chart and decide how to
    aggregate successful results and individual failures.
    """

    symbol: str
    scanned_at: pd.Timestamp
    scan_start: pd.Timestamp
    zones: list[dict[str, Any]]


CHART_SNAPSHOT_JAVASCRIPT = r"""
() => {
  function findChartWindow(win, depth = 5, seen = new Set()) {
    if (!win || depth < 0 || seen.has(win)) return null;
    seen.add(win);
    try {
      if (win.tradingViewApi && win.chartWidget) return win;
      for (const iframe of win.document.querySelectorAll('iframe')) {
        const found = findChartWindow(iframe.contentWindow, depth - 1, seen);
        if (found) return found;
      }
    } catch (_) {
      // A cross-origin frame cannot be inspected. Continue searching others.
    }
    return null;
  }

  const chartWindow = findChartWindow(window);
  if (!chartWindow) return { ready: false, reason: 'Kite chart API unavailable' };

  // Kite exposes chartWidget before its TradingView model is fully attached.
  // During that short interval model() throws "Value is null". Returning a
  // non-ready snapshot lets Python retry instead of terminating the scan.
  let bars;
  let chart;
  try {
    const model = chartWindow.chartWidget.model();
    if (!model) return { ready: false, reason: 'Kite chart model is initializing' };
    bars = model.mainSeries().bars()._items;
    chart = chartWindow.tradingViewApi.activeChart();
    if (!chart) return { ready: false, reason: 'Kite active chart is initializing' };
  } catch (error) {
    return { ready: false, reason: `Kite chart is initializing: ${error.message}` };
  }
  const candles = (Array.isArray(bars) ? bars : [])
    .map((bar) => ({
      timestamp: bar.timeMs,
      open: bar.value[1],
      high: bar.value[2],
      low: bar.value[3],
      close: bar.value[4],
      volume: bar.value[5] ?? 0,
    }))
    .filter((candle) => [
      candle.timestamp, candle.open, candle.high, candle.low, candle.close,
    ].every(Number.isFinite));

    return {
    ready: true,
    candles,
    earliestMs: candles.length ? Math.min(...candles.map((candle) => candle.timestamp)) : null,
    latestMs: candles.length ? Math.max(...candles.map((candle) => candle.timestamp)) : null,
    resolution: typeof chart.resolution === 'function' ? String(chart.resolution()) : null,
  };
}
"""


SET_RESOLUTION_JAVASCRIPT = r"""
(resolution) => {
  function findChartWindow(win, depth = 5, seen = new Set()) {
    if (!win || depth < 0 || seen.has(win)) return null;
    seen.add(win);
    try {
      if (win.tradingViewApi && win.chartWidget) return win;
      for (const iframe of win.document.querySelectorAll('iframe')) {
        const found = findChartWindow(iframe.contentWindow, depth - 1, seen);
        if (found) return found;
      }
    } catch (_) {}
    return null;
  }
  const chartWindow = findChartWindow(window);
  if (!chartWindow) return false;
  try {
    const chart = chartWindow.tradingViewApi.activeChart();
    if (!chart || typeof chart.setResolution !== 'function') return false;
    chart.setResolution(resolution);
    return true;
  } catch (_) {
    return false;
  }
}
"""


def two_years_ago(now: pd.Timestamp, years: int) -> pd.Timestamp:
    """Return the same local date N years ago, including a safe leap-day case."""

    try:
        return now.replace(year=now.year - years)
    except ValueError:  # 29 February -> 28 February in a non-leap year.
        return now.replace(year=now.year - years, month=2, day=28)


def resolution_is_two_hours(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"120", "2h", "2hour", "2hours"}


def as_kolkata_naive(value: Any) -> pd.Timestamp:
    """Normalize an API timestamp for safe comparison with scanner timestamps."""

    timestamp = pd.Timestamp(value)
    return timestamp.tz_convert("Asia/Kolkata").tz_localize(None) if timestamp.tzinfo else timestamp

def add_snapshot_candles(candles_by_timestamp: dict[int, dict[str, Any]], snapshot: dict[str, Any]) -> None:
    """Merge a loaded chart window without allowing duplicate timestamps."""

    for candle in snapshot["candles"]:
        candles_by_timestamp[int(candle["timestamp"])] = candle


async def verify_symbol_loaded(page: Any, configuration: ScanConfiguration, timeout_seconds: int = 30) -> None:
    """Fail clearly if Kite opened a different symbol (or none) than requested."""

    expected = configuration.symbol.split(":", maxsplit=1)[-1].upper()
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    title = ""
    while asyncio.get_running_loop().time() < deadline:
        title = (await page.title()).upper()
        if expected in title:
            return
        await page.wait_for_timeout(500)
    raise RuntimeError(
        f"Kite did not open {expected}; page title was {title!r} at {page.url}. "
        "Check the instrument token in the chart URL and that Brave is logged in to Kite."
    )


async def wait_for_chart(page: Any, timeout_seconds: int = 30) -> dict[str, Any]:
    """Wait until Kite exposes a valid TradingView candle buffer."""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_reason = "chart did not become ready"
    while asyncio.get_running_loop().time() < deadline:
        snapshot = await page.evaluate(CHART_SNAPSHOT_JAVASCRIPT)
        if snapshot.get("ready") and len(snapshot.get("candles", [])) >= 3:
            return snapshot
        last_reason = snapshot.get("reason", last_reason)
        await page.wait_for_timeout(500)
    raise RuntimeError(f"Timed out waiting for the Kite chart: {last_reason}.")


async def set_two_hour_resolution(page: Any, configuration: ScanConfiguration) -> None:
    """Set the chart to 120 minutes and verify it before reading history."""

    did_request_resolution = await page.evaluate(SET_RESOLUTION_JAVASCRIPT, configuration.resolution)
    if not did_request_resolution:
        raise RuntimeError("Kite did not expose activeChart().setResolution().")

    for _ in range(40):
        snapshot = await page.evaluate(CHART_SNAPSHOT_JAVASCRIPT)
        if snapshot.get("ready") and resolution_is_two_hours(snapshot.get("resolution")):
            return
        await page.wait_for_timeout(500)
    raise RuntimeError("Kite did not switch the chart to the required 2-hour timeframe.")


async def pan_chart_right(page: Any) -> None:
    """Drag the chart right once, requesting an older time window from Kite."""

    viewport = page.viewport_size or {"width": 1366, "height": 768}
    y = int(viewport["height"] * 0.62)
    start_x = int(viewport["width"] * 0.38)
    end_x = int(viewport["width"] * 0.82)

    await page.mouse.move(start_x, y)
    await page.mouse.down()
    await page.mouse.move(end_x, y, steps=12)
    await page.mouse.up()


async def collect_chart_history(page: Any, target_start: pd.Timestamp, configuration: ScanConfiguration) -> list[dict[str, Any]]:
    """Collect overlapping chart windows until the requested warm-up date is loaded.

    The job fails rather than writing a partial result if dragging no longer
    moves the earliest loaded candle before the requested start date.
    """

    target_start_ms = int(target_start.timestamp() * 1000)
    candles_by_timestamp: dict[int, dict[str, Any]] = {}
    stalled_attempts = 0
    maximum_stalled_attempts = 12

    for attempt in range(1, configuration.maximum_pan_attempts + 1):
        snapshot = await wait_for_chart(page)
        add_snapshot_candles(candles_by_timestamp, snapshot)
        earliest = snapshot["earliestMs"]

        if earliest is not None and earliest <= target_start_ms:
            LOG.info("Loaded history through %s after %d chart windows.", target_start.date(), attempt)
            return [candles_by_timestamp[key] for key in sorted(candles_by_timestamp)]


        LOG.info(
            "History window %d/%d: %d unique candles; earliest loaded: %s",
            attempt,
            configuration.maximum_pan_attempts,
            len(candles_by_timestamp),
            pd.to_datetime(earliest, unit="ms", utc=True).tz_convert("Asia/Kolkata") if earliest else "none",
        )
        await pan_chart_right(page)

        # Historical data arrives asynchronously. Wait up to five seconds for
        # the drag to produce an earlier candle before treating it as a stall.
        loaded_older_window = False
        for _ in range(10):
            await page.wait_for_timeout(500)
            updated_snapshot = await wait_for_chart(page)
            add_snapshot_candles(candles_by_timestamp, updated_snapshot)
            updated_earliest = updated_snapshot["earliestMs"]
            if updated_earliest is not None and updated_earliest < earliest:
                loaded_older_window = True
                break

        if loaded_older_window:
            stalled_attempts = 0
        else:
            stalled_attempts += 1
            LOG.warning(
                "Kite has not yet returned older candles after chart pan (%d/%d retries).",
                stalled_attempts,
                maximum_stalled_attempts,
            )
            if stalled_attempts >= maximum_stalled_attempts:
                raise RuntimeError(
                    "Kite stopped loading older candles before the required history was reached. "
                    "No zones.txt file was changed."
                )

    raise RuntimeError(
        f"Reached the safe limit of {configuration.maximum_pan_attempts} chart pans before loading {target_start.date()}. "
        "No zones.txt file was changed."
    )


def find_fresh_zones(candles: list[dict[str, Any]], scan_start: pd.Timestamp, configuration: ScanConfiguration) -> list[dict[str, Any]]:
    """Run the same detector, lifecycle, and LightGBM scoring flow as /scan."""

    try:
        import lightgbm as lgb
    except ImportError as error:
        raise RuntimeError("LightGBM is required to validate zones. Install the existing live-indicator dependencies.") from error

    model_path = PROJECT_DIRECTORY / "live_indicator" / "model" / "model.txt"
    if not model_path.is_file():
        raise RuntimeError(f"The existing LightGBM model was not found: {model_path}")

    dataframe, dropped = prepare_dataframe(candles)
    dataframe = drop_forming_candle(dataframe)
    candidates = [candidate for candidate in detect_once(dataframe) if candidate["start_index"] >= WARMUP_BARS]
    zones = build_zones(dataframe, candidates, configuration.symbol)

    # Keep candidate and zone ordering identical, exactly as unified_server_fixed.py does.
    model = lgb.Booster(model_file=str(model_path))
    scores = score_rows(candidate_rows(dataframe, candidates), model)
    for zone, score in zip(zones, scores):
        zone["ml"] = score

    fresh_zones = [
        zone
        for zone in zones
        if zone["status"] == "fresh" and as_kolkata_naive(zone["formed_at"]) >= scan_start
    ]
    fresh_zones.sort(key=lambda zone: (zone["formed_at"], zone["pattern_type"], zone["leg_out_mode"]))
    LOG.info(
        "Processed %d candles (%d invalid/duplicate dropped); found %d fresh zones, all LightGBM-scored.",
        len(dataframe),
        dropped,
        len(fresh_zones),
    )
    return fresh_zones


def write_zones(result: SymbolScanResult) -> None:
    """Atomically replace zones.txt only after a complete successful scan."""

    display_symbol = result.symbol.split(":", maxsplit=1)[-1]
    lines = [
        f"{display_symbol} fresh-zone scan",
        f"Scanned at (Asia/Kolkata): {result.scanned_at.isoformat()}",
        f"Zone formation period: {result.scan_start.date()} through {result.scanned_at.date()}",
        f"Fresh zones found: {len(result.zones)}",
        "",
    ]
    for number, zone in enumerate(result.zones, start=1):
        lines.extend(
            [
                f"[{number}] {zone['pattern_type']} {zone['leg_out_mode']}",
                f"  Formed: {zone['formed_at']}",
                f"  Zone: {zone['zone_low']:.2f} - {zone['zone_high']:.2f}",
                f"  Entry: {zone['entry']['final_entry']:.2f}",
                "  Lifecycle: PENDING / UNTOUCHED (fresh zone)",
                f"  ML: {zone['ml']['label'].upper()} | acceptance probability: {zone['ml']['p_accept'] * 100:.2f}%",
                f"  Zone ID: {zone['zone_id']}",
                f"  Details: {json.dumps(zone, sort_keys=True, default=str)}",
                "",
            ]
        )

    temporary_file = OUTPUT_FILE.with_suffix(".txt.tmp")
    temporary_file.write_text("\n".join(lines), encoding="utf-8")
    temporary_file.replace(OUTPUT_FILE)


async def scan_symbol(configuration: ScanConfiguration) -> SymbolScanResult:
    """Scan one configured Kite chart and return its fresh zones in memory.

    Browser automation and detector calls are unchanged from the original
    single-stock implementation. Errors deliberately propagate to the caller:
    a future batch runner will catch them per symbol so one failure cannot
    stop the remaining scans.
    """

    try:
        from playwright.async_api import async_playwright
    except ImportError as error:
        raise RuntimeError("Playwright is not installed. Run: py -m pip install -r crone-job/requirements.txt") from error

    scanned_at = pd.Timestamp.now(tz="Asia/Kolkata")
    scan_start = two_years_ago(scanned_at, configuration.history_years)
    warmup_start = scan_start - pd.Timedelta(days=configuration.warmup_days)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(configuration.cdp_url)
        if not browser.contexts:
            raise RuntimeError("Brave did not expose an authenticated browser context over CDP.")
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            await page.goto(configuration.chart_url, wait_until="domcontentloaded", timeout=45_000)
            await verify_symbol_loaded(page, configuration)
            await wait_for_chart(page)
            await set_two_hour_resolution(page, configuration)
            candles = await collect_chart_history(page, warmup_start, configuration)
        finally:
            # Never close the last tab: that would quit Brave and drop the CDP port.
            if len(context.pages) > 1:
                await page.close()

    zones = find_fresh_zones(candles, scan_start.tz_localize(None), configuration)
    return SymbolScanResult(
        symbol=configuration.symbol,
        scanned_at=scanned_at,
        scan_start=scan_start,
        zones=zones,
    )


async def run(configuration: ScanConfiguration) -> int:
    """Run the original one-symbol command and write its text result file."""

    result = await scan_symbol(configuration)
    write_zones(result)
    LOG.info("Saved complete scan result to %s", OUTPUT_FILE)
    return 0


def parse_arguments() -> ScanConfiguration:
    parser = argparse.ArgumentParser(description="Scan ICICIBANK's two-hour Kite history for fresh zones.")
    parser.add_argument("--cdp-url", default=ScanConfiguration.cdp_url, help="Brave remote-debugging URL (default: http://127.0.0.1:9222)")
    arguments = parser.parse_args()
    return ScanConfiguration(cdp_url=arguments.cdp_url)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return asyncio.run(run(parse_arguments()))
    except Exception as error:
        LOG.error("Fresh-zone scan failed: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
