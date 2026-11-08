# NIFTY 100 fresh-zone scanner (crone-job)

Downloads the official NIFTY 100 list, logs in to Kite (saved ID/password +
app code collected on Telegram), opens each stock's two-hour chart in your
Brave browser, loads ~2 years of history, and writes every untouched (`fresh`)
demand zone, scored by the LightGBM model, to `zones_nifty100.txt`.

It reuses the scanner functions in `../live_indicator/api` and changes nothing
there (no live API, Tampermonkey script, model or zone-history changes).
Keep `crone-job/`, `live_indicator/`, and `telegram/` side by side.

Telegram must already be set up (`python telegram/setup.py`). When the scan
starts you get a Telegram message; if Kite needs an app code, the bot asks for
the six digits there (up to three tries, 180 seconds each). When the batch
finishes, Telegram gets a short summary plus the zone details as chat messages.
The local `zones_nifty100.txt` report is still written on disk; a Telegram
delivery problem does not delete that file or change the scan result.

## Files

| File | Purpose |
|---|---|
| `run_nifty100.py` | **Main entry point** - login, resolve tokens, scan all symbols |
| `kite_login.py` | Saved-account login (passwords in Windows Credential Manager) |
| `kite_telegram.py` | Asks Telegram for the app code and submits it to Kite |
| `kite_instruments.py` | Symbol -> Kite instrument token -> chart URL |
| `nifty100.py` | Downloads/validates the official NIFTY 100 constituents |
| `batch_scan.py` | Scans many symbols; one failure never stops the batch |
| `scan_fresh_zones.py` | Scans one symbol's chart (also runnable on its own for ICICIBANK -> `zones.txt`) |
| `tests/` | Unit tests |

## One-time setup

```
python -m pip install -r crone-job/requirements.txt
python -m pip install -r telegram/requirements.txt
python telegram/setup.py
```

Close Brave completely, then start it with a debugging port and a separate
profile (recent Chromium browsers ignore the port on the default profile):

```
taskkill /F /IM brave.exe
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222 --user-data-dir="C:\brave-debug-profile"
```

Check `http://127.0.0.1:9222/json/version` shows JSON. Keep this Brave window open.

## Run (from the project root)

```
python crone-job/run_nifty100.py --limit 3     # quick test, first 3 stocks
python crone-job/run_nifty100.py               # full NIFTY 100 (about 2-2.5 hours)
```

If Brave is not logged in to Kite, saved passwords are used automatically and
the 6-digit app code is requested on Telegram. Later runs skip the app code
when the Brave profile is still logged in. Saved accounts are tried in order,
one attempt each; if one is rejected the next is used.

| Option | Meaning |
|---|---|
| `--add-account` | Save another Kite User ID + password |
| `--list-accounts` | Show saved IDs in retry order |
| `--remove-account ID` | Delete a saved account |
| `--skip-login` | Don't check or perform login |
| `--cdp-url URL` | Non-default debugging address |
| `--limit N` | Scan only the first N symbols |

Results are written to `crone-job/zones_nifty100.txt` only when the batch
finishes. Exit code 2 means at least one symbol failed (listed in the file).

## Troubleshooting

* `ECONNREFUSED 127.0.0.1:9222` - Brave is not running with the debugging port.
* `Kite did not open XYZ; page title was ...` - wrong token, login redirect, or
  not logged in; the message shows the page that actually opened.
* Symbols under "NO KITE TOKEN" were renamed/delisted on Kite.
* Login boxes not found - Kite changed its page; edit the selectors at the top
  of `kite_login.py`.

## Tests

```
python -m unittest discover -s crone-job/tests
```
