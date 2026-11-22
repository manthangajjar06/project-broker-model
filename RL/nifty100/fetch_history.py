"""Ask Kite for 1-minute history and write 2-hour files for the Nifty 100.

Nothing is requested until Zerodha accepts the enctoken. A symbol whose file
already has a footprint column is skipped, so a stopped run can continue.

    python fetch_history.py
    python fetch_history.py --symbol ICICIBANK
    python fetch_history.py --limit 3
"""

from __future__ import annotations

import argparse
import getpass
import time

from chart import CDP_URL, ensure_brave
from constituents import load_nifty100_symbols
from history import (
    HistoryError,
    TokenRejected,
    build_symbol,
    confirm_enctoken,
    decode_kite_body,
    has_footprint,
    normalize_token,
    now_minutes_ist,
    today_ist,
)
from indicators import csv_path
from instruments import parse_equity_tokens, load_instrument_csv

READ_TOKEN_JS = r"""
() => {
  function fromWindow(win) {
    try {
      const storage = win.localStorage;
      const direct = storage.getItem("enctoken");
      const userId = storage.getItem("user_id") || storage.getItem("public_id") || "";
      if (direct) return { token: direct, userId };
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index) || "";
        const value = storage.getItem(key) || "";
        if (/enctoken/i.test(key) && value && !value.trim().startsWith("{") && !value.trim().startsWith("[")) {
          return { token: value, userId };
        }
        if (!value.includes("enctoken")) continue;
        try {
          const data = JSON.parse(value);
          const token = data && (data.enctoken || data.enc_token);
          if (token) return { token: String(token), userId: String(data.user_id || data.userId || userId || "") };
        } catch (_) {}
      }
    } catch (_) {}
    return null;
  }
  const found = fromWindow(window);
  if (found) return found;
  for (const frame of document.querySelectorAll("iframe")) {
    try {
      const inner = fromWindow(frame.contentWindow);
      if (inner) return inner;
    } catch (_) {}
  }
  return null;
}
"""


def kite_page(browser):
    for context in browser.contexts:
        for page in context.pages:
            if "kite.zerodha.com" in (page.url or ""):
                return page
    return None


def session_on_page(page) -> tuple[str, str]:
    found = page.evaluate(READ_TOKEN_JS) or {}
    return normalize_token(found.get("token") or ""), str(found.get("userId") or "").strip()


def browser_get(page, authorization):
    """Call Kite with the browser's cookies, without the page rewriting the header."""

    def get(url: str, _authorization: str) -> tuple[int, dict]:
        response = page.context.request.get(
            url,
            headers={
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.6",
                "authorization": authorization,
                "referer": "https://kite.zerodha.com/static/chart/tradingview/chart.html",
            },
            timeout=60_000,
        )
        return response.status, decode_kite_body(response.text())

    return get


def run_batch(
    symbols, tokens, authorization, user_id, end, now_minutes, get,
    sleep=None, log=print,
):
    saved, skipped, failed = [], [], []
    for symbol in symbols:
        path = csv_path(symbol)
        if has_footprint(path):
            log(f"skip {symbol}")
            skipped.append(symbol)
            continue
        instrument = tokens.get(symbol)
        if instrument is None:
            log(f"failed {symbol}: no Kite instrument token")
            failed.append((symbol, "no Kite instrument token"))
            continue
        try:
            written, odd_days = build_symbol(
                get, authorization, symbol, str(instrument), user_id, end, now_minutes,
                sleep or time.sleep, log,
            )
            special = [day for day in odd_days if day["special"]]
            for day in special:
                log(f"  {symbol} {day['date']} {day['first_minute']} -> {day['last_minute']} anchor {day['anchor']}")
            log(f"saved {written}")
            saved.append(symbol)
        except TokenRejected:
            raise
        except Exception as error:
            log(f"failed {symbol}: {error}")
            failed.append((symbol, str(error)))
    return saved, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Nifty 100 2-hour history from Kite's 1-minute server.")
    parser.add_argument("--symbol", default="", help="Only this trading symbol.")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N symbols. 0 means all 100.")
    parser.add_argument("--enctoken", default="", help="Zerodha enctoken. Leave empty to read it from the open Kite tab.")
    parser.add_argument("--cdp-url", default=CDP_URL)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    ensure_brave(args.cdp_url)
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        page = kite_page(browser)
        if page is None:
            print("Open a logged-in Kite tab in the debug browser, then run this again. No history request was sent.")
            return
        found_token, found_user = session_on_page(page)
        authorization = normalize_token(args.enctoken) or found_token
        if authorization and not args.enctoken:
            print("Read the Zerodha enctoken from the open Kite tab.")
        if not authorization:
            pasted = getpass.getpass("Paste the Zerodha enctoken (blank to stop): ").strip()
            authorization = normalize_token(pasted)
        if not authorization:
            print("Stopped. Zerodha enctoken was not available, so no history request was sent.")
            return

        get = browser_get(page, authorization)
        try:
            user_id = confirm_enctoken(authorization, get, user_id=found_user)
        except TokenRejected as error:
            print(f"Stopped. {error} No history request was sent.")
            return
        except HistoryError as error:
            print(f"Stopped. {error} No history request was sent.")
            return

        who = f" for {user_id}" if user_id else ""
        print(f"Zerodha enctoken accepted{who}. Starting the Nifty 100 history load.")
        symbols = (args.symbol.strip().upper(),) if args.symbol else load_nifty100_symbols()
        if args.limit:
            symbols = symbols[: args.limit]
        tokens = parse_equity_tokens(load_instrument_csv())
        try:
            saved, skipped, failed = run_batch(
                symbols, tokens, authorization, user_id, today_ist(), now_minutes_ist(), get,
            )
        except TokenRejected as error:
            print(f"Stopped. {error}")
            return
        print(f"saved {len(saved)} | skipped {len(skipped)} | failed {len(failed)}")


if __name__ == "__main__":
    main()
