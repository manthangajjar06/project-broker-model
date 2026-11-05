# crone-job speed report — why the NIFTY 100 scan is slow and how to fix it safely

Scope: `crone-job/` (NIFTY 100 fresh-zone scanner). Nothing was changed in your project for this report. Everything below is either **measured** (I ran your real detector and model on synthetic candles), **read from your code/log**, or an **estimate** that I flag as such. I could not run Brave or log in to Kite here, so the browser-side numbers must be confirmed with the instrumentation in section 3 before any optimisation is trusted.

---

## 1. Summary

- A full run takes about 2–2.5 hours (your README), which is roughly **70–90 seconds per symbol**.
- **Measured:** the Python side (detect zones, build features, LightGBM score) costs about **1 second per symbol**. Details are in section 2. So over 98% of the time is spent waiting on the browser, not computing.
- The time is spent in four places, in this order of likely impact:
  1. **Loading 2+ years of chart history by dragging the chart** (`collect_chart_history`). It uses fixed 500 ms sleeps and downloads the *entire* candle list again on every 500 ms poll.
  2. **Everything runs one symbol at a time**, one tab, no overlap (`batch_scan.py`).
  3. **Per-symbol fixed overhead**: a new Playwright/Node process and CDP connection per symbol, a new tab, a full Kite page load, and several 500 ms polling loops.
  4. **Dead time on symbols that can never succeed** (recently listed stocks): 12 retries × 5 s = about 60 s wasted, then a failure.
- Realistic target after all three phases in section 6: **about 3–5x faster (2–2.5 h down to roughly 30–50 min)**. This is an estimate, not a promise. It depends on how many pans Kite needs per symbol, which the instrumentation will tell us.
- Identical output is protected by a before/after comparison on the same symbols (section 7). No phase is accepted unless that comparison matches exactly.

---

## 2. Where the time goes (evidence)

### 2.1 Measured: the Python/CPU part is small

I ran your real `scan_support_fixed`, `detector`, `DRBR`, `feature_engineering` and `model.txt` on 2,356 synthetic 2-hour candles (about 2.3 years, 4 bars per day):

| Step | Time |
|---|---|
| `import lightgbm` (first symbol only, cached afterwards) | 1.02 s |
| Load `model.txt` | 0.013 s |
| `prepare_dataframe` | 0.198 s |
| `detect_once` (DRBR rules + SUPER candidates) | 0.649 s |
| `build_zones` | 0.032 s |
| `candidate_rows` | 0.051 s |
| `score_rows` (LightGBM predict) | 0.020 s |
| **Total per symbol (after first)** | **≈ 1.0 s** |

Over 100 symbols that is about 100 s out of 7,200–9,000 s. Rewriting the detector would save about 1% of the run and carries real risk to results, so **it is not recommended** (see section 5, item 11).

### 2.2 Read from your log: fixed overhead per Playwright session

Your earlier log shows two Node driver start-ups (the `DEP0169` warning) about 40 seconds apart, one for login and one for the scan. Timeline from that run:

| Time | Event |
|---|---|
| 08:50:35 | Brave debugging endpoint ready |
| 08:50:47 | "Trying saved account" (about 12 s for Playwright start-up, opening Kite, checking login) |
| 08:51:20 | Logged in (mostly you typing the app code) |
| 08:51:27 | First scan attempted (about 7 s of overhead: list download, token lookup, a new Playwright/Node start) |

`scan_symbol` does the same Playwright start-up and CDP connect **for every symbol** (`scan_fresh_zones.py` lines 398–399). That is a repeated cost of several seconds per symbol that buys nothing, because the browser is the same one every time.

### 2.3 Read from the code: the history loop is the main cost

`collect_chart_history` (`scan_fresh_zones.py`) works like this:

1. Take a full snapshot of the chart (`wait_for_chart`).
2. If the earliest candle is not old enough, drag the chart right once (`pan_chart_right`).
3. Poll up to 10 times: sleep **500 ms**, then take another **full snapshot**, until an older candle appears.
4. Repeat, up to 240 pans. If 12 pans in a row bring no new data, fail.

Problems with this design:

- **A fixed 500 ms sleep before every poll** puts a floor of 0.5 s on every pan, even when Kite answers in 100 ms.
- **Every snapshot ships the whole candle list**: `CHART_SNAPSHOT_JAVASCRIPT` maps and returns every loaded bar. At 2,356 candles that is about **260 KB of plain JSON per poll** (measured), and Playwright's own value encoding makes the real transfer larger. The cost grows as history grows, so late pans are the most expensive.
- **Two snapshots where one would do**: the loop takes a snapshot at the top of every pan, but the previous iteration's last poll already produced it.
- **`wait_for_chart` is a polling loop inside a polling loop**: each of the 10 polls can itself retry every 500 ms.
- **Dragging a chart with the mouse is slow and fragile.** It moves 44% of the screen width per drag, so history loads in many small steps.
- **A stalled symbol wastes about 60 seconds**: 12 stalled pans × up to 5 s each. This is the case for any stock listed less than about 2.25 years ago, which can never reach the target date. The symbol ends as a failure anyway.

Other fixed waits per symbol: `verify_symbol_loaded` (500 ms poll, up to 30 s), `wait_for_chart` (500 ms poll), `set_two_hour_resolution` (500 ms poll, up to 20 s), plus `page.goto` of the full Kite single-page app each time.

### 2.4 What I could not measure

How many pans Kite needs per symbol, how long each Kite response takes, and how long the page load takes. These decide how the 70–90 s splits across the points above. Section 3 gives the exact way to measure them.

---

## 3. How to debug it properly (do this before changing anything)

Goal: a timing table per symbol that shows exactly where the 70–90 seconds go. This adds logging only and changes no behaviour.

### 3.1 Add a small stopwatch

Put this in a new file `crone-job/timing.py`:

```python
import time, json, logging
from contextlib import contextmanager
from pathlib import Path

LOG = logging.getLogger("timing")
_records: list[dict] = []

@contextmanager
def timed(symbol: str, stage: str, **extra):
    start = time.perf_counter()
    try:
        yield
    finally:
        _records.append({"symbol": symbol, "stage": stage, "seconds": round(time.perf_counter() - start, 3), **extra})

def dump(path: Path) -> None:
    path.write_text(json.dumps(_records, indent=1), encoding="utf-8")
```

### 3.2 Wrap these stages in `scan_symbol` and `collect_chart_history`

| Stage name | Where |
|---|---|
| `playwright_start_connect` | `async_playwright()` start plus `connect_over_cdp` |
| `new_page_goto` | `context.new_page()` plus `page.goto(...)` |
| `verify_symbol` | `verify_symbol_loaded` |
| `wait_chart` | first `wait_for_chart` |
| `set_resolution` | `set_two_hour_resolution` |
| `history` | whole `collect_chart_history` |
| `detect_score` | `find_fresh_zones` |

Inside `collect_chart_history` also count and log: **pans performed**, **snapshots taken**, **seconds per pan** (min / median / max), **stalled pans**, and the **candle count at each pan**. Write the result with `dump(...)` to `crone-job/timing_nifty100.json` at the end of the batch.

### 3.3 Run two probes

1. `python crone-job/run_nifty100.py --limit 5` and read `timing_nifty100.json`. This gives the split between page load, history loading and everything else.
2. Run once with a **long-history stock** and once with a **recently listed stock** to see the stall cost.

### 3.4 How to read the result

| If you see | Then |
|---|---|
| `history` is more than about 70% of symbol time | Phase 1 and the JS-range idea (section 5.1 to 5.4) are the priority |
| `playwright_start_connect` is more than 2 s | Connection reuse (5.5) is a quick win |
| `new_page_goto` is more than 5 s | Reusing a tab or switching symbol in place (5.6) is worth it |
| Median seconds per pan is close to 0.5–1 s | The fixed 500 ms sleep is the floor; shrink it (5.1) |
| Pans per symbol is more than about 50 | Loading history in bigger steps (5.4) gives the largest saving |
| Stall retries appear on some symbols | Early stop for impossible history (5.8) |

For the Python part, `python -m cProfile -s cumtime` on `find_fresh_zones` confirms section 2.1 on your own machine in a minute.

---

## 4. Ground rules so nothing existing breaks

- **No change to detection, features, scoring, thresholds or output format.** `scan_support_fixed.py`, `detector.py`, `DRBR.py`, `feature_engineering.py` and `model.txt` stay as they are.
- **Same candles in = same zones out.** Speed work only changes *how* candles are collected, never what is done with them.
- **Per-symbol failure isolation stays.** One failed symbol never stops the batch.
- **Every speed change is switchable.** Each new behaviour sits behind a flag or a try/except fallback to the current behaviour.
- **Each phase must pass the comparison in section 7** before the next phase starts.

---

## 5. Optimisations, ranked

| # | Change | Where | Est. saving | Risk to results | Effort |
|---|---|---|---|---|---|
| 1 | Poll every 100–150 ms instead of 500 ms | `collect_chart_history`, `wait_for_chart`, `verify_symbol_loaded`, `set_two_hour_resolution` | High | None | Low |
| 2 | Light probe on each poll (earliest bar + count only); full candle read only when new data arrived | `collect_chart_history`, new JS probe | High | None if the final candle set is identical | Low–Med |
| 3 | Remove the duplicate snapshot at the top of each pan | `collect_chart_history` | Low–Med | None | Low |
| 4 | Load history in bigger steps (wider drag, or ask the chart for the target date range in JS) | `pan_chart_right` / new JS | **Very high** | Medium, needs the comparison | Med |
| 5 | One Playwright connection for the whole batch | `scan_symbol`, `run_nifty100` | Med | Low | Med |
| 6 | One reusable tab, or change symbol in place | `scan_symbol` | Med | Medium | Med |
| 7 | Scan 2–3 symbols at the same time | `batch_scan.py` | **Very high** | Medium | Med–High |
| 8 | Stop early when Kite has no older data | `collect_chart_history` | Only affects failing symbols | Low | Low |
| 9 | Run CPU work off the event loop (needed once #7 is on) | `scan_symbol` | Enables #7 | None | Low |
| 10 | Save results as symbols finish, allow resume | `run_nifty100.py` | Reliability | None | Low |
| 11 | Rewrite detector loops | `DRBR.py` | About 1% | **High** | High, **not recommended** |
| 12 | Call Kite's chart-data endpoint directly instead of the chart | new module | Very high | High, terms-of-service and format risk | High, **only as a last resort** |

### 5.1 Poll fast, not slow (items 1 and 3)

Replace the fixed `wait_for_timeout(500)` polls with 100–150 ms polls and the same overall timeouts, so worst-case behaviour is unchanged but the typical case is several times quicker. Drop the redundant top-of-loop snapshot by reusing the last one taken in the previous iteration.

### 5.2 Stop downloading the whole candle list on every poll (item 2)

Add a second, tiny JS function that returns only `{ready, earliestMs, count, resolution}`. Use it for every poll. Call the full snapshot **only** when `earliestMs` changed (new data actually arrived) and once more at the end. The union-by-timestamp merge that already exists is kept, so the final candle set is the same, and each poll shrinks from hundreds of KB to a few bytes.

### 5.3 Why the merge logic stays

`add_snapshot_candles` merges every snapshot by timestamp. That suggests the chart's in-memory bars may not always keep everything. I will therefore not assume that a single final snapshot is enough. The light-probe approach in 5.2 keeps full merges at each *change* and removes only the useless ones.

### 5.4 Load history in far fewer steps (item 4, biggest single win)

Today history arrives in many small drag-sized steps. Two options, in order of preference:

1. **Ask the chart for the whole range in one go.** TradingView charts expose a visible-range call (`activeChart().setVisibleRange({from, to})`), and Kite's chart is a TradingView widget. If it works here, one call can trigger loading all the way back to `warmup_start`, replacing dozens of drags. The existing code already finds `activeChart()` and calls `setResolution`, so the foothold exists. **I have not verified that Kite's build allows it**; it must be tried on one symbol. If the call is missing or does not load the data, the code falls back to dragging exactly as it does today.
2. **Drag further per pan.** Increase the drag distance, or drag several times before reading. Simple, less risky, smaller gain.

This also removes the dependence on mouse focus, which matters for item 7.

### 5.5 Reuse one browser connection (item 5)

Open `async_playwright()` and `connect_over_cdp` once in `run_nifty100.py` and pass the browser/context into `scan_symbol` (an optional parameter, so the standalone `scan_fresh_zones.py` command keeps working unchanged). Per-symbol isolation stays: if the shared connection is lost, reconnect for the next symbol. This removes a Node process start (several seconds) per symbol.

### 5.6 Don't reload the whole Kite app for every symbol (item 6)

Options: keep one tab and `goto` the next chart URL, or switch the symbol inside the chart through the widget API. The first is simple and low risk. The second is faster but less certain on Kite; try it only after the measurements show page load is a large share.

### 5.7 Scan 2–3 symbols at once (items 7 and 9, biggest multiplier)

`batch_scan.py` runs strictly one symbol at a time. Its comment says this is because "one chart's history loading should complete before the next chart changes", but separate tabs in the same logged-in profile do not interfere with each other's charts, so the original reason is weaker than it looks. Plan:

- Use a small `asyncio.Semaphore` (start with **2**, try 3). Do not go high, to avoid hitting Kite rate limits.
- **Background tabs are throttled by Chromium.** Timers slow down and charts may not load history while hidden. Mitigate by adding these flags to the Brave launch command in `run_nifty100.py`: `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows`. If throttling still bites, open each worker in its own window.
- Mouse-drag history loading needs a focused tab, so **parallelism depends on 5.4 option 1** (JS range request). Test that first.
- Move `find_fresh_zones` into `asyncio.to_thread(...)` (item 9). Today CPU work runs on the same loop as the browser polling, which would stall the other tabs.
- Keep the final list **in the original symbol order** so the output file is the same.

### 5.8 Stop early on stocks that can't reach 2 years (item 8)

For a recently listed stock Kite never returns candles older than the listing date, so the loop spends 12 × 5 s = about 60 s and then fails. Keep the same outcome (a recorded failure with the same message), but detect "no more data" sooner, for example when the earliest bar has not moved after 3–4 fast polls *and* the chart reports it has reached the end of data. I have not confirmed which flag Kite's widget exposes for end-of-data; check this during measurement. Until confirmed, just shorten the stall wait, which keeps behaviour identical.

### 5.9 Save as you go (item 10, reliability not speed)

Results are written only at the very end (`write_batch`). A crash at symbol 95 loses 2 hours of work. Write after each symbol (or each few symbols) to a temp file and add a `--resume` flag that skips symbols already done. The final file format stays the same.

### 5.10 Why not rewrite the detector (item 11)

It is about 0.65 s per symbol out of 70–90 s. Converting its `df.iloc[i]` loops to plain records would be faster, but the saving is about 1% of the run and any slip changes which zones are found. Not worth it.

### 5.11 About calling Kite's data endpoint directly (item 12)

Kite's web chart loads candles from an internal historical-data endpoint that returns long ranges in a single request, which would make each symbol take seconds. I list it only for completeness. It is an internal, unofficial endpoint, authenticated by your browser session; it may break without notice, may conflict with Zerodha's terms, and returns data in a different format than the chart widget, so equality with today's results would need careful checking. The official, supported alternative is Kite Connect's historical-data API (a paid subscription). Please decide on that yourself, and I would only look at it if the safer phases below fall short.

---

## 6. Rollout plan

| Phase | Contents | Expected effect | Gate to continue |
|---|---|---|---|
| **0. Measure** | Section 3 instrumentation only | None, gives the numbers | Timing table collected |
| **1. Safe** | Items 1, 2, 3, 8 (shorter stall wait only), 10 | Noticeably faster history loading, no change to what is loaded | Output identical on 5 symbols (section 7) |
| **2. Connection reuse** | Items 5 and 6 (simple `goto` version) | Removes per-symbol start-up cost | Output identical; failure isolation test passes |
| **3. Bigger history steps** | Item 4, JS range request with drag fallback | Biggest per-symbol cut, if Kite allows it | Candle set identical to the old method on 5 symbols |
| **4. Parallel** | Items 7 and 9 with 2, then 3 workers | Roughly 2–3x on top of the above | Output identical; no new failures vs sequential |

Estimate: phases 1–3 should cut each symbol from 70–90 s to roughly 20–40 s *if* history loading is the dominant cost, as the code suggests. Phase 4 then divides the wall-clock time by about 2–3, so a full run lands in the **30–50 minute** range. If the Phase 0 numbers differ (for example, Kite itself is slow to answer), these figures need to be revised.

---

## 7. Proving that nothing changed (golden-master check)

Do this for every phase:

1. **Freeze a baseline** with the *current* code, on the same day and after market close so the last candle and the 2-year start date are the same:
   `python crone-job/run_nifty100.py --limit 5`, then copy `zones_nifty100.txt` to `baseline_5.txt`.
2. Also dump the raw candle list for each symbol to a JSON file during the baseline run (one extra line in `scan_symbol`), so candles can be compared separately from zones.
3. Run the **new** code the same way and compare:
   - **Candles**: same count, same first and last timestamp, same hash of the sorted list. (The old method may load slightly more or fewer bars before the start date; what matters is that every bar from `scan_start` onward is identical, because that is what produces the zones.)
   - **Zones**: same `zone_id`, `formed_at`, `zone_low`, `zone_high`, `entry`, `ml.label`, `ml.p_accept` for every zone, same order.
   - **Failures and "No Kite token" lists**: same symbols and same messages.
4. Run the unit tests: `python -m unittest discover -s crone-job/tests`. At the start of this analysis they pass: **23 tests, all OK** on the full project.
5. Add unit tests for every new piece, using fake page objects (as `test_kite_login.py` already does): light probe, merge-on-change, early stall stop, connection-lost-then-reconnect, and parallel ordering.
6. For Phase 4, additionally run the full list once sequentially and once in parallel, and diff the two output files. They must match exactly (except the timestamp line).

---

## 8. Things I noticed along the way (not speed, worth a look)

- **Short-history symbols fail the whole symbol.** `collect_chart_history` raises if Kite stops returning older candles before the 2-year target, even though plenty of recent data exists. That is existing behaviour and I would keep it unless you decide otherwise; it also means these symbols cost about 60 s each before failing.
- **`extract_features` calls `drop_duplicates()` and `reset_index()` on the candidate rows**, but `find_fresh_zones` pairs scores to zones with `zip(zones, scores)`. If two candidate rows were ever identical, the scores would silently shift against the zones. Identical rows look practically impossible (they contain different indices and timestamps), so this is a latent risk only, in the live-indicator code, which I did not touch.
- **`scan_fresh_zones.py` has mixed Windows and Unix line endings** inside the embedded JavaScript strings. Harmless at runtime, but it can make diffs noisy.
- **The archive extracted incompletely with some tools.** Several files (`detector.py`, `unified_server.py`, two test files, one Tampermonkey script) came out empty with the first extractor and were fine with another. If you re-zip the project for sharing, a `.zip` avoids that.

---

## 9. What I need from you to proceed

1. Approval to do **Phase 0** (instrumentation only) first, then share `timing_nifty100.json` from a `--limit 5` run, so the plan can be tuned to real numbers.
2. Whether **parallel scanning** (2–3 tabs) is acceptable for your Zerodha account usage, since it makes several chart loads happen at the same time.
3. Whether you want **resume and incremental saving** (5.9) included.
