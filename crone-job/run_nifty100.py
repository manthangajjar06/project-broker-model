"""Manual entry point: download NIFTY 100, resolve Kite tokens, scan every chart.

Run from the project root:
    python crone-job/run_nifty100.py [--cdp-url http://127.0.0.1:9222] [--limit 5]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

JOB_DIRECTORY = Path(__file__).resolve().parent
if str(JOB_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(JOB_DIRECTORY))

from batch_scan import BatchScanResult, scan_configurations  # noqa: E402
from kite_instruments import chart_url, resolve_symbols  # noqa: E402
from kite_login import ensure_logged_in, list_accounts, prompt_and_save_account, remove_account  # noqa: E402
from nifty100 import load_nifty100_constituents  # noqa: E402
from scan_fresh_zones import ScanConfiguration  # noqa: E402

LOG = logging.getLogger("run_nifty100")
OUTPUT_FILE = JOB_DIRECTORY / "zones_nifty100.txt"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_BRAVE_EXECUTABLE = Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
DEFAULT_BRAVE_PROFILE = Path(r"C:\brave-debug-profile")
CDP_STARTUP_TIMEOUT_SECONDS = 30


def _cdp_is_ready(cdp_url: str) -> bool:
    """Return whether a Chromium DevTools endpoint is responding."""
    version_url = f"{cdp_url.rstrip('/')}/json/version"
    try:
        with urlopen(version_url, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError):
        return False
    return bool(payload.get("webSocketDebuggerUrl"))


def ensure_brave_running(
    cdp_url: str,
    brave_executable: Path = DEFAULT_BRAVE_EXECUTABLE,
    profile_directory: Path = DEFAULT_BRAVE_PROFILE,
) -> None:
    """Launch the dedicated local Brave CDP profile when it is not running."""
    if _cdp_is_ready(cdp_url):
        LOG.info("Brave debugging endpoint is already ready at %s.", cdp_url)
        return

    endpoint = urlparse(cdp_url)
    if endpoint.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(
            f"The remote debugging endpoint is not reachable: {cdp_url}. "
            "Automatic Brave startup is only available for local endpoints."
        )
    if not brave_executable.is_file():
        raise RuntimeError(f"Brave executable was not found: {brave_executable}")

    port = endpoint.port or 9222
    command = [
        str(brave_executable),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_directory}",
    ]
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    LOG.info("Starting Brave with remote debugging on port %d...", port)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )

    deadline = time.monotonic() + CDP_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _cdp_is_ready(cdp_url):
            LOG.info("Brave debugging endpoint is ready.")
            return
        if process.poll() is not None:
            break
        time.sleep(0.25)

    raise RuntimeError(
        f"Brave was started but its debugging endpoint did not become ready at {cdp_url}. "
        "Close any other Brave windows and run the scanner again."
    )


def build_configurations(symbols, cdp_url):
    resolved = resolve_symbols(list(symbols))
    for name in resolved.unresolved:
        LOG.warning("No NSE equity token in Kite's list for %s (renamed/delisted?) - skipped.", name)
    return [
        ScanConfiguration(symbol=f"NSE:{name}", chart_url=chart_url(name, token), cdp_url=cdp_url)
        for name, token in resolved.tokens.items()
    ], resolved.unresolved


def write_batch(batch: BatchScanResult, unresolved) -> None:
    lines = [
        f"NIFTY 100 fresh-zone scan  ({batch.completed_at.isoformat()})",
        f"Scanned OK: {len(batch.successful_scans)} | Failed: {len(batch.failures)} | No Kite token: {len(unresolved)}",
        "",
    ]
    for scan in batch.successful_scans:
        lines.append(f"=== {scan.symbol}: {len(scan.zones)} fresh zones ===")
        for n, zone in enumerate(scan.zones, 1):
            lines.append(
                f"[{n}] {zone['pattern_type']} {zone['leg_out_mode']} | formed {zone['formed_at']} | "
                f"zone {zone['zone_low']:.2f}-{zone['zone_high']:.2f} | entry {zone['entry']['final_entry']:.2f} | "
                f"ML {zone['ml']['label'].upper()} {zone['ml']['p_accept'] * 100:.2f}%"
            )
            lines.append(f"    Details: {json.dumps(zone, sort_keys=True, default=str)}")
        lines.append("")
    if batch.failures:
        lines.append("=== FAILURES ===")
        lines += [f"{f.symbol}: {f.error_type}: {f.message}" for f in batch.failures]
    if unresolved:
        lines.append("=== NO KITE TOKEN ===")
        lines.append(", ".join(unresolved))
    tmp = OUTPUT_FILE.with_suffix(".txt.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(OUTPUT_FILE)


async def login_if_needed(cdp_url: str) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("Brave did not expose a browser context over CDP.")
        await ensure_logged_in(browser.contexts[0])


async def main_async(cdp_url: str, limit: int | None, skip_login: bool = False) -> int:
    await asyncio.to_thread(ensure_brave_running, cdp_url)
    if not skip_login:
        await login_if_needed(cdp_url)
        if not _cdp_is_ready(cdp_url):
            # Brave exited after login; relaunch it (the profile keeps the session) and re-check login.
            LOG.warning("Brave stopped after login; restarting it.")
            await asyncio.to_thread(ensure_brave_running, cdp_url)
            await login_if_needed(cdp_url)
    symbols = load_nifty100_constituents().symbols
    if limit:
        symbols = symbols[:limit]
    configurations, unresolved = build_configurations(symbols, cdp_url)
    batch = await scan_configurations(configurations)
    write_batch(batch, unresolved)
    LOG.info("Saved %s", OUTPUT_FILE)
    return 0 if not batch.failures else 2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--limit", type=int, default=None, help="Only scan the first N symbols (for testing)")
    parser.add_argument("--add-account", action="store_true", help="Save a Kite User ID + password, then exit")
    parser.add_argument("--list-accounts", action="store_true", help="Show saved User IDs, then exit")
    parser.add_argument("--remove-account", metavar="USER_ID", help="Delete a saved account, then exit")
    parser.add_argument("--skip-login", action="store_true", help="Do not check or perform Kite login")
    args = parser.parse_args()

    if args.add_account:
        prompt_and_save_account()
        return 0
    if args.list_accounts:
        print("Saved accounts (retry order):", ", ".join(list_accounts()) or "none")
        return 0
    if args.remove_account:
        print("Removed." if remove_account(args.remove_account) else "No such saved account.")
        return 0
    return asyncio.run(main_async(args.cdp_url, args.limit, args.skip_login))


if __name__ == "__main__":
    raise SystemExit(main())
