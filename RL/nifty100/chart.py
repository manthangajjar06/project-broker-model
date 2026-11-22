"""Drag the Kite chart's bottom date axis until older 2-hour candles stop.

The drag matches the chart gesture: press the left side of the date row
(Nov, 5, 11, 16) and pull across to its right edge. One drag shows many
months. Repeat until the oldest candle no longer moves.

    python chart.py
    python chart.py --symbol INFY
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from indicators import write_csv
from instruments import resolve_chart_urls

CDP_URL = "http://127.0.0.1:9222"
BRAVE = Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
BRAVE_PROFILE = Path(r"C:\brave-debug-profile")
IST = ZoneInfo("Asia/Kolkata")

SNAPSHOT_JS = r"""
() => {
  function findChart(win, depth = 5, seen = new Set()) {
    if (!win || depth < 0 || seen.has(win)) return null;
    seen.add(win);
    try {
      if (win.tradingViewApi && win.chartWidget) return win;
      for (const frame of win.document.querySelectorAll('iframe')) {
        const found = findChart(frame.contentWindow, depth - 1, seen);
        if (found) return found;
      }
    } catch (_) {}
    return null;
  }
  const chartWindow = findChart(window);
  if (!chartWindow) return { ready: false, reason: 'chart api missing' };
  try {
    const model = chartWindow.chartWidget.model();
    const items = model.mainSeries().bars()._items;
    const list = Array.isArray(items) ? items : Object.values(items || {});
    const candles = list.filter(Boolean).map((bar) => ({
      timestamp: bar.timeMs ?? bar.value[0],
      open: bar.value[1], high: bar.value[2], low: bar.value[3], close: bar.value[4],
      volume: bar.value[5] ?? 0,
    })).filter((bar) => [bar.timestamp, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite));
    const chart = chartWindow.tradingViewApi.activeChart();
    return {
      ready: candles.length > 0,
      reason: candles.length ? '' : 'no candles yet',
      candles,
      resolution: chart && typeof chart.resolution === 'function' ? String(chart.resolution()) : '',
    };
  } catch (error) {
    return { ready: false, reason: String(error) };
  }
}
"""

SET_RESOLUTION_JS = r"""
(resolution) => {
  function findChart(win, depth = 5, seen = new Set()) {
    if (!win || depth < 0 || seen.has(win)) return null;
    seen.add(win);
    try {
      if (win.tradingViewApi && win.chartWidget) return win;
      for (const frame of win.document.querySelectorAll('iframe')) {
        const found = findChart(frame.contentWindow, depth - 1, seen);
        if (found) return found;
      }
    } catch (_) {}
    return null;
  }
  const chartWindow = findChart(window);
  if (!chartWindow) return false;
  const chart = chartWindow.tradingViewApi.activeChart();
  if (!chart || typeof chart.setResolution !== 'function') return false;
  chart.setResolution(resolution);
  return true;
}
"""


def ist_text(timestamp: int) -> str:
    millis = timestamp if timestamp > 10_000_000_000 else timestamp * 1000
    return datetime.fromtimestamp(millis / 1000, IST).strftime("%Y-%m-%d %H:%M")


def cdp_ready(cdp_url: str) -> bool:
    try:
        with urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=2) as response:
            return "webSocketDebuggerUrl" in json.loads(response.read().decode())
    except (OSError, URLError, ValueError):
        return False


def ensure_brave(cdp_url: str) -> None:
    """Start the separate debug Brave only when the port is closed."""
    if cdp_ready(cdp_url):
        return
    if not BRAVE.is_file():
        raise RuntimeError(f"Brave was not found at {BRAVE}, and {cdp_url} is not open.")
    port = cdp_url.rsplit(":", 1)[-1].strip("/")
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(BRAVE), f"--remote-debugging-port={port}", f"--user-data-dir={BRAVE_PROFILE}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if cdp_ready(cdp_url):
            return
        time.sleep(0.25)
    raise RuntimeError(f"Brave did not open a debugging port at {cdp_url}.")


def wait_for_chart(page, timeout_seconds: int = 40) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last = {"reason": "chart did not load"}
    while time.monotonic() < deadline:
        last = page.evaluate(SNAPSHOT_JS)
        if last.get("ready"):
            return last
        page.wait_for_timeout(500)
    raise RuntimeError(f"Chart did not load: {last.get('reason')}. Log in to Kite in the debug Brave window.")


def set_two_hour(page) -> None:
    if not page.evaluate(SET_RESOLUTION_JS, "120"):
        raise RuntimeError("Could not set the chart to 2 hours.")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        snapshot = page.evaluate(SNAPSHOT_JS)
        if snapshot.get("ready") and str(snapshot.get("resolution", "")).lower() in {"120", "2h"}:
            return
        page.wait_for_timeout(500)
    raise RuntimeError("The chart did not switch to 2 hours.")


def date_axis_box(page) -> dict:
    """The bottom date row the user circled, not the candles above it."""
    found = []
    for frame in page.frames:
        locator = frame.locator("td.time-axis, .time-axis")
        for index in range(locator.count()):
            box = locator.nth(index).bounding_box()
            if box and box["width"] > 120 and box["height"] >= 8:
                found.append(box)
    if not found:
        raise RuntimeError("Could not find the chart date axis.")
    return max(found, key=lambda box: box["y"])


def drag_horizontal(page, box: dict, y_ratio: float, start_ratio: float, end_ratio: float) -> None:
    y = box["y"] + box["height"] * y_ratio
    start_x = box["x"] + box["width"] * start_ratio
    end_x = box["x"] + box["width"] * end_ratio
    page.mouse.move(start_x, y)
    page.mouse.down()
    page.wait_for_timeout(100)
    page.mouse.move(end_x, y, steps=30)
    page.wait_for_timeout(100)
    page.mouse.up()


def drag_date_axis(page) -> None:
    """Squeeze the date row from its left edge to its right edge."""
    drag_horizontal(page, date_axis_box(page), 0.5, 0.02, 0.98)
    print("  squeezed date axis")


def candle_pane_box(page) -> dict:
    """The price plot above the date row. Dragging here pans without changing the squeeze."""
    found = []
    for frame in page.frames:
        locator = frame.locator("td.pane")
        for index in range(locator.count()):
            box = locator.nth(index).bounding_box()
            if box and box["width"] > 200 and box["height"] > 80:
                found.append(box)
    if not found:
        axis = date_axis_box(page)
        return {"x": axis["x"], "y": max(0, axis["y"] - 320), "width": axis["width"], "height": 260}
    return max(found, key=lambda box: box["width"] * box["height"])


def pan_backward(page) -> None:
    """Shift the squeezed chart toward older candles."""
    drag_horizontal(page, candle_pane_box(page), 0.45, 0.20, 0.80)
    print("  panned backward")


def merge(store: dict[int, dict], snapshot: dict) -> None:
    for candle in snapshot["candles"]:
        stamp = int(candle["timestamp"])
        store[stamp] = candle


def earliest_of(store: dict[int, dict]) -> int | None:
    return min(store) if store else None


def left_edge(snapshot: dict) -> int:
    return min(int(candle["timestamp"]) for candle in snapshot["candles"])


def settled_left_edge(page, store: dict[int, dict], before: int) -> int:
    """The chart's left edge once it has stopped moving after a drag."""
    last = None
    same = 0
    while True:
        page.wait_for_timeout(500)
        snapshot = page.evaluate(SNAPSHOT_JS)
        if not snapshot.get("ready"):
            continue
        merge(store, snapshot)
        edge = left_edge(snapshot)
        if edge == last:
            same += 1
            # An older edge means this drag moved the window. The old edge has
            # to sit still before we accept that the window refused to move.
            if edge < before or same >= 4:
                return edge
        else:
            last = edge
            same = 1


def move_until_still(page, store: dict[int, dict], action, label: str) -> None:
    snapshot = wait_for_chart(page)
    merge(store, snapshot)
    edge = left_edge(snapshot)
    move = 0
    while True:
        move += 1
        print(f"{label} {move}: {len(store)} candles, {ist_text(min(store))} -> {ist_text(max(store))}", flush=True)
        action(page)
        after = settled_left_edge(page, store, edge)
        print(f"  window {ist_text(edge)} -> {ist_text(after)}", flush=True)
        if after >= edge:
            print(f"{label} stopped. The window did not move.", flush=True)
            return
        edge = after


def scroll_until_end(page) -> dict[int, dict]:
    store: dict[int, dict] = {}
    move_until_still(page, store, drag_date_axis, "squeeze")
    move_until_still(page, store, pan_backward, "pan")
    return store


def load_symbol(page, symbol: str, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    deadline = time.monotonic() + 40
    title = ""
    while time.monotonic() < deadline:
        try:
            title = page.title()
        except Exception:
            page.wait_for_timeout(500)
            continue
        if symbol in title.upper():
            return
        page.wait_for_timeout(500)
    address = page.url
    if "login" in address or "login" in title.lower():
        raise RuntimeError(f"Kite is not logged in. Open {address} in the debug Brave window and log in, then run this again.")
    raise RuntimeError(f"Kite opened {title!r} at {address} instead of {symbol}.")


def scrape_on_page(page, symbol: str, url: str) -> dict[int, dict]:
    load_symbol(page, symbol, url)
    wait_for_chart(page)
    set_two_hour(page)
    return scroll_until_end(page)


def scroll_symbol(symbol: str, cdp_url: str = CDP_URL) -> dict[int, dict]:
    from playwright.sync_api import sync_playwright

    urls, _missing = resolve_chart_urls([symbol])
    if symbol not in urls:
        raise RuntimeError(f"Kite has no NSE equity chart for {symbol}.")
    ensure_brave(cdp_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("The debug browser has no window.")
        page = browser.contexts[0].new_page()
        return scrape_on_page(page, symbol, urls[symbol])


def main() -> None:
    parser = argparse.ArgumentParser(description="Drag one Kite 2-hour chart back to its oldest candle.")
    parser.add_argument("--symbol", default="ICICIBANK")
    parser.add_argument("--cdp-url", default=CDP_URL)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    candles = scroll_symbol(symbol, args.cdp_url)
    path = write_csv(symbol, candles)
    earliest = min(candles)
    latest = max(candles)
    print(f"{symbol}: {len(candles)} candles, {ist_text(earliest)} -> {ist_text(latest)}")
    print(f"saved {path}")


if __name__ == "__main__":
    main()
