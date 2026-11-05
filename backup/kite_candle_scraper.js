// =============================================================================
// Zerodha Kite — ChartIQ Candlestick Scraper v2 (Console Snippet)
// =============================================================================
// USAGE:
//   1. Open Zerodha Kite in Chrome → open a chart for any stock
//   2. Open DevTools (F12) → Console tab (keep context as "top")
//   3. Paste this entire script and press Enter
//   4. Scroll back on the chart to load more historical candles — they are
//      captured automatically via network interception
//   5. When you've scrolled to the stock's listing date (earliest data):
//        → Type  downloadCandlesCSV()   to save as CSV
//        → Type  downloadCandlesJSON()  to save as JSON
//   6. Switching to a different stock? Type  clearCandles()  first
//
// COMMANDS:
//   downloadCandlesCSV()   — Download all captured candles as a CSV file
//   downloadCandlesJSON()  — Download all captured candles as a JSON file
//   clearCandles()         — Reset captured data (use when switching stocks)
//   candleStatus()         — Print summary: count, date range, etc.
//   diagnose()             — Debug: show detected iframes, stxx, interceptors
// =============================================================================

(function () {
  'use strict';

  // ── Prevent double-init ──────────────────────────────────────────────────
  if (window.__kiteScraperActive) {
    console.warn(
      '[Scraper] Already running. Use clearCandles() to reset data, ' +
      'or reload the page to fully re-initialize.'
    );
    return;
  }
  window.__kiteScraperActive = true;

  // ── Storage (always on top window) ───────────────────────────────────────
  window.scrapedCandles = [];
  const _seen = new Set();
  const _log = []; // diagnostic log
  let _skippedDirty = 0; // count of filtered-out dirty candles
  let _ohlcWarnings = 0; // count of OHLC-invalid candles (kept but flagged)

  function log(msg) {
    const entry = `[${new Date().toLocaleTimeString()}] ${msg}`;
    _log.push(entry);
    console.log(`%c[Scraper] ${msg}`, 'color:#00e676; font-weight:bold');
  }

  function warn(msg) {
    const entry = `[${new Date().toLocaleTimeString()}] ⚠ ${msg}`;
    _log.push(entry);
    console.warn(`[Scraper] ${msg}`);
  }

  // ── Timestamp normalization ──────────────────────────────────────────────
  function tsKey(raw) {
    try {
      return new Date(raw).toISOString();
    } catch {
      return String(raw);
    }
  }

  // ── Parse a single candle into canonical shape ───────────────────────────
  function parseCandle(c) {
    if (Array.isArray(c)) {
      return {
        timestamp: c[0],
        open: c[1],
        high: c[2],
        low: c[3],
        close: c[4],
        volume: c[5],
        oi: c[6] ?? 0,
      };
    }
    if (c && (c.DT || c.Date)) {
      return {
        timestamp: c.DT
          ? (typeof c.DT.toISOString === 'function' ? c.DT.toISOString() : String(c.DT))
          : c.Date,
        open: c.Open,
        high: c.High,
        low: c.Low,
        close: c.Close,
        volume: c.Volume ?? 0,
        oi: c.OI ?? 0,
      };
    }
    return c;
  }

  /**
   * Check if a candle is clean intraday data (not a phantom daily aggregate).
   * Kite's API sometimes returns an extra "day" summary candle at 00:00:00
   * alongside the regular 2-hour intraday candles — these are redundant.
   */
  function isCleanCandle(candle) {
    try {
      const dt = new Date(candle.timestamp);
      const hours = dt.getHours();
      const minutes = dt.getMinutes();
      const seconds = dt.getSeconds();

      // Filter out midnight candles (00:00:00) — these are day-level aggregates
      if (hours === 0 && minutes === 0 && seconds === 0) {
        return false;
      }
      return true;
    } catch {
      return true; // if we can't parse, keep it and let the user decide
    }
  }

  /**
   * Check OHLC validity: High >= all, Low <= all.
   */
  function isOHLCValid(c) {
    return c.high >= c.open && c.high >= c.close && c.high >= c.low &&
           c.low <= c.open && c.low <= c.close && c.low <= c.high;
  }

  // ── Dedup + merge new candles ────────────────────────────────────────────
  function addCandles(rawCandles, source) {
    let added = 0;
    let skipped = 0;
    for (const raw of rawCandles) {
      const candle = parseCandle(raw);
      if (!candle || candle.open == null) continue;

      // Filter out dirty candles (phantom midnight aggregates)
      if (!isCleanCandle(candle)) {
        skipped++;
        _skippedDirty++;
        continue;
      }

      // Flag OHLC-invalid candles (keep them, but count for diagnostics)
      if (!isOHLCValid(candle)) {
        _ohlcWarnings++;
      }

      const key = tsKey(candle.timestamp);
      if (_seen.has(key)) continue;
      _seen.add(key);
      window.scrapedCandles.push(candle);
      added++;
    }
    if (added > 0 || skipped > 0) {
      window.scrapedCandles.sort(
        (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
      );
      let msg = `+${added} candles from ${source}  |  Total: ${window.scrapedCandles.length}`;
      if (skipped > 0) msg += `  |  🧹 ${skipped} dirty candles filtered out`;
      log(msg);
    }
  }

  // ── Collect all reachable window contexts ────────────────────────────────
  const _injectedContexts = new WeakSet();
  const _diagInfo = {
    iframesFound: 0,
    iframesInjected: 0,
    iframeSrcs: [],
    stxxFound: false,
    stxxContext: null,
    interceptedUrls: [],
  };

  function getAllContexts() {
    const contexts = [{ win: window, label: 'top' }];
    try {
      const iframes = document.querySelectorAll('iframe');
      _diagInfo.iframesFound = iframes.length;
      iframes.forEach((iframe, i) => {
        try {
          const cw = iframe.contentWindow;
          // This will throw if cross-origin
          const _test = cw.location.href;
          const src = iframe.src || iframe.getAttribute('src') || `iframe-${i}`;
          contexts.push({ win: cw, label: src });
          if (!_diagInfo.iframeSrcs.includes(src)) {
            _diagInfo.iframeSrcs.push(src);
          }
        } catch {
          // cross-origin — skip
        }
      });
    } catch { /* ignore */ }
    return contexts;
  }

  // ── Inject fetch + XHR interceptors into a window context ────────────────
  function injectInterceptors(targetWin, label) {
    if (_injectedContexts.has(targetWin)) return;
    _injectedContexts.add(targetWin);

    // ---- fetch ----
    try {
      const origFetch = targetWin.fetch;
      if (typeof origFetch === 'function') {
        targetWin.fetch = async function (...args) {
          const response = await origFetch.apply(this, args);
          try {
            const url = typeof args[0] === 'string'
              ? args[0]
              : (args[0]?.url ?? '');
            if (url.includes('/instruments/historical/')) {
              _diagInfo.interceptedUrls.push({ type: 'fetch', label, url });
              const clone = response.clone();
              clone.json().then((data) => {
                if (data?.status === 'success' && data?.data?.candles?.length) {
                  const tag = url.split('?')[0].split('/').slice(-2).join('/');
                  addCandles(data.data.candles, `fetch [${label}] ${tag}`);
                }
              }).catch(() => { });
            }
          } catch { /* swallow */ }
          return response;
        };
        log(`fetch interceptor installed on [${label}]`);
      }
    } catch (e) {
      warn(`Could not install fetch interceptor on [${label}]: ${e.message}`);
    }

    // ---- XMLHttpRequest ----
    try {
      const origOpen = targetWin.XMLHttpRequest.prototype.open;
      const origSend = targetWin.XMLHttpRequest.prototype.send;

      targetWin.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
        this.__scraperUrl = url;
        this.__scraperLabel = label;
        return origOpen.call(this, method, url, ...rest);
      };

      targetWin.XMLHttpRequest.prototype.send = function (...args) {
        const url = this.__scraperUrl || '';
        if (url.includes('/instruments/historical/')) {
          _diagInfo.interceptedUrls.push({ type: 'XHR', label, url });
          this.addEventListener('load', function () {
            try {
              const data = JSON.parse(this.responseText);
              if (data?.status === 'success' && data?.data?.candles?.length) {
                const tag = url.split('?')[0].split('/').slice(-2).join('/');
                addCandles(data.data.candles, `XHR [${label}] ${tag}`);
              }
            } catch { /* ignore */ }
          });
        }
        return origSend.apply(this, args);
      };
      log(`XHR interceptor installed on [${label}]`);
    } catch (e) {
      warn(`Could not install XHR interceptor on [${label}]: ${e.message}`);
    }
  }

  // ── Grab pre-loaded ChartIQ data from any context ───────────────────────
  function grabChartIQ() {
    const contexts = getAllContexts();

    for (const { win: ctx, label } of contexts) {
      try {
        // Try common global names for ChartIQ engine
        const candidates = [
          ctx.stxx,
          ctx.stx,
          ctx.stxEngine,
          ctx.chartEngine,
        ];

        for (const stxx of candidates) {
          if (!stxx) continue;

          if (stxx.masterData?.length) {
            _diagInfo.stxxFound = true;
            _diagInfo.stxxContext = label;
            addCandles(stxx.masterData, `ChartIQ masterData [${label}]`);
            return true;
          }
          if (stxx.chart?.dataSet?.length) {
            _diagInfo.stxxFound = true;
            _diagInfo.stxxContext = label;
            addCandles(stxx.chart.dataSet, `ChartIQ dataSet [${label}]`);
            return true;
          }
          if (stxx.chart?.masterData?.length) {
            _diagInfo.stxxFound = true;
            _diagInfo.stxxContext = label;
            addCandles(stxx.chart.masterData, `ChartIQ chart.masterData [${label}]`);
            return true;
          }
        }

        // Fallback: look for CIQ global and registered containers
        if (ctx.CIQ) {
          const containers = ctx.CIQ.ChartEngine?.registeredContainers;
          if (containers) {
            const engines = Array.isArray(containers)
              ? containers
              : Object.values(containers);
            for (const engine of engines) {
              if (engine?.masterData?.length) {
                _diagInfo.stxxFound = true;
                _diagInfo.stxxContext = label;
                addCandles(engine.masterData, `CIQ engine [${label}]`);
                return true;
              }
            }
          }
        }

        // Fallback: walk window properties looking for anything with masterData
        // (limited depth to avoid performance issues)
        for (const key of Object.keys(ctx)) {
          try {
            const obj = ctx[key];
            if (obj && typeof obj === 'object' && obj.masterData?.length > 10) {
              _diagInfo.stxxFound = true;
              _diagInfo.stxxContext = `${label}.${key}`;
              addCandles(obj.masterData, `${key}.masterData [${label}]`);
              return true;
            }
          } catch { /* skip non-readable props */ }
        }
      } catch { /* skip context */ }
    }

    return false;
  }

  // ── Install interceptors in ALL reachable contexts ───────────────────────
  function installAll() {
    const contexts = getAllContexts();
    for (const { win, label } of contexts) {
      injectInterceptors(win, label);
    }
    _diagInfo.iframesInjected = contexts.length - 1; // minus top
  }

  // Run immediately
  installAll();
  grabChartIQ();

  // Re-scan periodically (iframes may load late, new data may appear)
  const _pollInterval = setInterval(() => {
    installAll();  // catches any newly-added iframes
    grabChartIQ(); // grabs data from ChartIQ objects
  }, 3000);

  // ── Download helpers ─────────────────────────────────────────────────────
  function downloadBlob(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  window.downloadCandlesCSV = function () {
    const candles = window.scrapedCandles;
    if (!candles.length) {
      console.warn('[Scraper] No candles captured yet — nothing to download.');
      return;
    }

    const header = 'Date,Time,Timestamp,Open,High,Low,Close,Volume,OI';
    const rows = candles.map((c) => {
      const dt = new Date(c.timestamp);
      const date = dt.getFullYear() + '-' +
        String(dt.getMonth() + 1).padStart(2, '0') + '-' +
        String(dt.getDate()).padStart(2, '0');
      const time = String(dt.getHours()).padStart(2, '0') + ':' +
        String(dt.getMinutes()).padStart(2, '0') + ':' +
        String(dt.getSeconds()).padStart(2, '0');
      const ts = `${date} ${time}`;
      return `${date},${time},${ts},${c.open},${c.high},${c.low},${c.close},${c.volume},${c.oi}`;
    });

    const csv = [header, ...rows].join('\n');
    const filename = `candles_${candles.length}_${Date.now()}.csv`;
    downloadBlob(csv, filename, 'text/csv');
    console.log(
      `%c[Scraper] ✅ Downloaded ${candles.length} candles → ${filename}`,
      'color:#00e676; font-weight:bold; font-size:13px'
    );
  };

  window.downloadCandlesJSON = function () {
    const candles = window.scrapedCandles;
    if (!candles.length) {
      console.warn('[Scraper] No candles captured yet — nothing to download.');
      return;
    }

    const json = JSON.stringify(candles, null, 2);
    const filename = `candles_${candles.length}_${Date.now()}.json`;
    downloadBlob(json, filename, 'application/json');
    console.log(
      `%c[Scraper] ✅ Downloaded ${candles.length} candles → ${filename}`,
      'color:#00e676; font-weight:bold; font-size:13px'
    );
  };

  window.clearCandles = function () {
    window.scrapedCandles = [];
    _seen.clear();
    _skippedDirty = 0;
    _ohlcWarnings = 0;
    console.log(
      '%c[Scraper] 🗑️  All candles cleared. Ready for a new stock.',
      'color:#ff9800; font-weight:bold'
    );
  };

  window.candleStatus = function () {
    const candles = window.scrapedCandles;
    if (!candles.length) {
      console.log('%c[Scraper] No candles captured yet.', 'color:#ff9800');
      return;
    }
    const first = new Date(candles[0].timestamp);
    const last = new Date(candles[candles.length - 1].timestamp);
    console.log(
      `%c[Scraper] 📊 ${candles.length} clean candles captured\n` +
      `   Earliest : ${first.toLocaleString()}\n` +
      `   Latest   : ${last.toLocaleString()}\n` +
      `   🧹 Filtered out : ${_skippedDirty} dirty candles (midnight aggregates)\n` +
      `   ⚠️  OHLC warnings: ${_ohlcWarnings}`,
      'color:#42a5f5; font-weight:bold; font-size:12px'
    );
  };

  // ── Diagnostic command ───────────────────────────────────────────────────
  window.diagnose = function () {
    console.group('%c[Scraper] 🔍 Diagnostics', 'color:#42a5f5; font-weight:bold; font-size:13px');

    console.log(`Iframes found on page: ${_diagInfo.iframesFound}`);
    console.log(`Iframes successfully injected: ${_diagInfo.iframesInjected}`);
    if (_diagInfo.iframeSrcs.length) {
      console.log('Iframe sources:');
      _diagInfo.iframeSrcs.forEach((s) => console.log(`  • ${s}`));
    }

    console.log(`ChartIQ stxx found: ${_diagInfo.stxxFound}`);
    if (_diagInfo.stxxContext) {
      console.log(`  → in context: ${_diagInfo.stxxContext}`);
    }

    console.log(`Intercepted API calls so far: ${_diagInfo.interceptedUrls.length}`);
    _diagInfo.interceptedUrls.forEach((u) => {
      console.log(`  [${u.type}] [${u.label}] ${u.url.substring(0, 120)}`);
    });

    console.log(`Candles captured: ${window.scrapedCandles.length}`);
    console.log(`Dirty candles filtered out: ${_skippedDirty} (midnight aggregates)`);
    console.log(`OHLC-invalid candles (kept): ${_ohlcWarnings}`);

    console.log('\n--- Recent log ---');
    _log.slice(-15).forEach((l) => console.log(l));

    // Show what globals exist in accessible iframes
    console.log('\n--- Searching for chart objects ---');
    const contexts = getAllContexts();
    for (const { win: ctx, label } of contexts) {
      try {
        const checks = {
          'stxx': !!ctx.stxx,
          'stx': !!ctx.stx,
          'CIQ': !!ctx.CIQ,
          'stxEngine': !!ctx.stxEngine,
          'chartEngine': !!ctx.chartEngine,
          'TradingView': !!ctx.TradingView,
          'tvWidget': !!ctx.tvWidget,
        };
        const found = Object.entries(checks).filter(([, v]) => v).map(([k]) => k);
        if (found.length) {
          console.log(`  [${label}] Found: ${found.join(', ')}`);
        } else {
          console.log(`  [${label}] No chart objects found`);
        }
      } catch (e) {
        console.log(`  [${label}] Cannot access: ${e.message}`);
      }
    }

    console.groupEnd();

    console.log(
      '\n%c[Scraper] 💡 If no API calls are being intercepted, try:\n' +
      '  1. Scroll back on the chart to trigger a data load\n' +
      '  2. Switch the timeframe (e.g. 1D → 1H → 1D)\n' +
      '  3. If using an iframe, change Console context dropdown to the chart iframe\n' +
      '     and paste the script there instead',
      'color:#ff9800; font-size:11px'
    );
  };

  // ── Startup banner ───────────────────────────────────────────────────────
  const ctxCount = getAllContexts().length;
  console.log(
    '%c[Scraper] 🚀 Kite Candle Scraper v2 is ACTIVE\n' +
    `%c  • Interceptors installed in ${ctxCount} context(s) (top + ${ctxCount - 1} iframe(s))\n` +
    '  • Scroll back on the chart — candles are captured automatically\n' +
    '  • Commands:\n' +
    '      candleStatus()        — count & date range\n' +
    '      downloadCandlesCSV()  — save as CSV\n' +
    '      downloadCandlesJSON() — save as JSON\n' +
    '      clearCandles()        — reset for a new stock\n' +
    '      diagnose()            — debug: show detected contexts & chart objects',
    'color:#00e676; font-weight:bold; font-size:14px',
    'color:#b0bec5; font-size:11px'
  );

})();