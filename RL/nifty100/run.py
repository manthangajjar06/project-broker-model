"""Scrape 2-hour history for the current Nifty 100 list.

One symbol failing does not stop the others. A symbol that already has a CSV
is skipped, so a stopped run can be started again.

    python run.py --limit 3
    python run.py
"""

from __future__ import annotations

import argparse

from chart import CDP_URL, ensure_brave, scrape_on_page
from constituents import load_nifty100_symbols
from indicators import csv_path, write_csv
from instruments import resolve_chart_urls


def run_batch(symbols, urls, scrape, already_saved):
    saved, skipped, failed = [], [], []
    for symbol in symbols:
        if already_saved(symbol):
            print(f"skip {symbol}")
            skipped.append(symbol)
            continue
        if symbol not in urls:
            print(f"failed {symbol}: no Kite chart")
            failed.append((symbol, "no Kite chart"))
            continue
        try:
            scrape(symbol, urls[symbol])
            saved.append(symbol)
        except Exception as error:
            print(f"failed {symbol}: {error}")
            failed.append((symbol, str(error)))
            if "not logged in" in str(error):
                break
    return saved, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape 2-hour candles for the Nifty 100.")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N symbols. 0 means all 100.")
    parser.add_argument("--cdp-url", default=CDP_URL)
    args = parser.parse_args()

    symbols = load_nifty100_symbols()
    if args.limit:
        symbols = symbols[: args.limit]
    urls, _missing = resolve_chart_urls(symbols)
    ensure_brave(args.cdp_url)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            raise RuntimeError("The debug browser has no window.")
        page = browser.contexts[0].new_page()

        def scrape(symbol: str, url: str) -> None:
            candles = scrape_on_page(page, symbol, url)
            path = write_csv(symbol, candles)
            print(f"saved {path}")

        saved, skipped, failed = run_batch(symbols, urls, scrape, lambda symbol: csv_path(symbol).is_file())

    print(f"saved {len(saved)} | skipped {len(skipped)} | failed {len(failed)}")


if __name__ == "__main__":
    main()
