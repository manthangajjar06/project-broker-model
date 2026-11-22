// Zerodha Kite candle scraper. Paste the whole file into the chart-page console.
//
// 1. Open the Kite chart (ChartIQ or TradingView).
// 2. F12 → Console → paste → Enter.
// 3. loadAllHistory()     full history, timestamps taken from Kite's own payload
//    or scroll the chart  captures whatever the chart loads
// 4. downloadCandlesCSV()
//
// Timestamps are NSE/IST wall-clock. A "+0530" string is kept as written.
// It is never converted with toISOString().
//
// upper_wick_pct, lower_wick_pct, body_pct are shares of that candle's
// high-low range and sum to 100. ATR(14) is Wilder, SMA-seeded.
// DATR is the previous completed session's daily ATR (Wilder, span 14).
// avg_volume_14d is the mean volume of the previous 14 completed sessions.

(function () {
    'use strict';
    if (window.__kiteScraperActive) {
      console.warn('[Scraper] Already running. Reload the page to paste a new copy.');
      return;
    }
    window.__kiteScraperActive = true;
  
    const IST_OFFSET_MS = 330 * 60 * 1000;
    const buckets = new Map();
    let authHeader = null;
  
    function pad(n) { return String(n).padStart(2, '0'); }
  
    function istToEpoch(date, time) {
      const [Y, M, D] = date.split('-').map(Number);
      const [h, m, s] = time.split(':').map(Number);
      return Date.UTC(Y, M - 1, D, h, m || 0, s || 0) - IST_OFFSET_MS;
    }
  
    function fmtIst(ms) {
      const bag = {};
      for (const p of new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Kolkata', hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      }).formatToParts(new Date(ms))) {
        if (p.type !== 'literal') bag[p.type] = p.value;
      }
      if (bag.hour === '24') bag.hour = '00';
      const date = `${bag.year}-${bag.month}-${bag.day}`;
      const time = `${bag.hour}:${bag.minute}:${bag.second}`;
      return { date, time, timestamp: `${date} ${time}` };
    }
  
    function clockFromEpoch(ms, mode) {
      if (mode === 'ist') return fmtIst(ms);
      const d = new Date(ms);
      const date = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
      const time = `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
      return { date, time, timestamp: `${date} ${time}` };
    }
  
    function toMins(time) {
      const [h, m] = time.split(':').map(Number);
      return h * 60 + m;
    }
  
    function parseRawTimestamp(raw) {
      if (typeof raw === 'string') {
        const m = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/);
        if (!m) return null;
        const date = m[1];
        const time = m[2];
        const tz = m[3] || '';
        if (!tz || tz === '+0530' || tz === '+05:30') {
          return { date, time, timestamp: `${date} ${time}`, epoch_ms: istToEpoch(date, time), time_source: 'ist_string', timestamp_raw: raw };
        }
        const iso = /[+-]\d{4}$/.test(raw) ? raw.replace(/([+-]\d{2})(\d{2})$/, '$1:$2') : raw;
        const ms = Date.parse(iso);
        if (!Number.isFinite(ms)) return null;
        return { ...fmtIst(ms), epoch_ms: ms, time_source: 'instant', timestamp_raw: raw };
      }
      if (raw instanceof Date && Number.isFinite(raw.getTime())) {
        return { epoch_ms: raw.getTime(), time_source: 'epoch', timestamp_raw: raw.toISOString() };
      }
      if (typeof raw === 'number' && Number.isFinite(raw)) {
        return { epoch_ms: raw > 1e12 ? raw : raw * 1000, time_source: 'epoch', timestamp_raw: String(raw) };
      }
      return null;
    }
  
    (function selfTest() {
      const a = parseRawTimestamp('2017-12-15T09:15:00+0530');
      const b = parseRawTimestamp('2017-12-15T03:45:00Z');
      const midnight = parseRawTimestamp('2024-01-02T00:00:00+0530');
      if (!a || a.timestamp !== '2017-12-15 09:15:00') throw new Error('IST string parse failed');
      if (!b || b.timestamp !== '2017-12-15 09:15:00' || b.epoch_ms !== a.epoch_ms) throw new Error('UTC instant parse failed');
      if (!midnight || midnight.timestamp !== '2024-01-02 00:00:00') throw new Error('midnight IST parse failed');
      if (fmtIst(a.epoch_ms).timestamp !== a.timestamp) throw new Error('IST round-trip failed');
    })();
  
    function num(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    }
  
    function parseCandle(raw) {
      let ts;
      let o;
      let h;
      let l;
      let c;
      let v = 0;
      if (Array.isArray(raw)) {
        ts = parseRawTimestamp(raw[0]);
        o = num(raw[1]); h = num(raw[2]); l = num(raw[3]); c = num(raw[4]);
        v = num(raw[5]) ?? 0;
      } else if (raw && raw.value && (raw.timeMs != null || raw.value[0] != null)) {
        ts = parseRawTimestamp(raw.timeMs ?? raw.value[0]);
        o = num(raw.value[1]); h = num(raw.value[2]); l = num(raw.value[3]); c = num(raw.value[4]);
        v = num(raw.value[5]) ?? 0;
      } else if (raw && (raw.DT || raw.Date || raw.date || raw.timestamp)) {
        ts = parseRawTimestamp(raw.DT || raw.Date || raw.date || raw.timestamp);
        o = num(raw.Open ?? raw.open); h = num(raw.High ?? raw.high);
        l = num(raw.Low ?? raw.low); c = num(raw.Close ?? raw.close);
        v = num(raw.Volume ?? raw.volume) ?? 0;
      }
      if (!ts || o == null || h == null || l == null || c == null) return null;
      return { ...ts, open: o, high: h, low: l, close: c, volume: v };
    }
  
    function symbolNow() {
      const hrefs = [location.href];
      document.querySelectorAll('iframe').forEach((f) => { try { hrefs.push(f.contentWindow.location.href); } catch (_) {} });
      for (const href of hrefs) {
        const m = href.match(/\/(NSE|BSE|NFO|MCX|CDS|BCD)\/([^/]+)\/(\d+)/i);
        if (m) return { symbol: `${m[1].toUpperCase()}:${decodeURIComponent(m[2]).toUpperCase()}`, token: m[3] };
      }
      const title = document.title.match(/([A-Z0-9&.\-]+) \((NSE|BSE|NFO|MCX|CDS)\)/i);
      return { symbol: title ? `${title[2].toUpperCase()}:${title[1].toUpperCase()}` : '', token: '' };
    }
  
    function tvInterval() {
      const map = { 1: 'minute', 3: '3minute', 5: '5minute', 10: '10minute', 15: '15minute', 30: '30minute', 60: '60minute', 120: '120minute', '1D': 'day', D: 'day', '1W': 'week', W: 'week', '1M': 'month', M: 'month' };
      const wins = [window];
      document.querySelectorAll('iframe').forEach((f) => { try { wins.push(f.contentWindow); } catch (_) {} });
      for (const win of wins) {
        try {
          const res = win.tradingViewApi?.activeChart?.().resolution?.();
          if (res != null && map[res]) return map[res];
        } catch (_) {}
      }
      return '';
    }
  
    function bucketFor(token, interval) {
      const id = `${token || symbolNow().symbol || 'chart'}|${interval || 'unknown'}`;
      if (!buckets.has(id)) buckets.set(id, { id, token, interval, symbol: symbolNow().symbol, rows: new Map(), lastUrl: '' });
      const b = buckets.get(id);
      if (token) b.token = token;
      if (interval) b.interval = interval;
      if (!b.symbol) b.symbol = symbolNow().symbol;
      return b;
    }
  
    function addCandles(list, meta) {
      const b = bucketFor(meta.token, meta.interval);
      if (meta.url) b.lastUrl = meta.url;
      let n = 0;
      for (const raw of list) {
        const candle = parseCandle(raw);
        if (!candle) continue;
        const key = candle.time_source === 'ist_string' ? `s|${candle.timestamp}` : `e|${candle.epoch_ms}`;
        b.rows.set(key, candle);
        n++;
      }
      if (n) console.log(`%c[Scraper] ${b.symbol || b.token} ${b.interval}: ${b.rows.size} candles`, 'color:#00e676;font-weight:bold');
    }
  
    function ingestPayload(data, url) {
      const candles = data?.data?.candles || data?.candles;
      if (!Array.isArray(candles) || !candles.length) return;
      const m = String(url).match(/\/historical\/(\d+)\/([^/?]+)/);
      addCandles(candles, { token: m ? m[1] : '', interval: m ? decodeURIComponent(m[2]) : tvInterval(), url: String(url) });
    }
  
    function rememberAuth(value) {
      if (typeof value === 'string' && /enctoken|authorization/i.test(value) && value.length > 12) authHeader = value;
    }
  
    function patchWindow(win, label) {
      if (!win || win.__kiteScraperPatched) return;
      try { win.__kiteScraperPatched = true; } catch (_) { return; }
      try {
        if (typeof win.authHeader === 'string') rememberAuth(win.authHeader.startsWith('enctoken') ? win.authHeader : `enctoken ${win.authHeader}`);
      } catch (_) {}
  
      try {
        const orig = win.fetch;
        if (typeof orig === 'function') {
          win.fetch = function (...args) {
            try {
              const headers = args[1]?.headers;
              const auth = headers?.get?.('authorization') || headers?.Authorization || headers?.authorization;
              rememberAuth(auth);
            } catch (_) {}
            return orig.apply(this, args).then((res) => {
              try {
                const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                if (url.includes('/historical/')) res.clone().json().then((data) => ingestPayload(data, url)).catch(() => {});
              } catch (_) {}
              return res;
            });
          };
        }
      } catch (_) {}
  
      try {
        const XHR = win.XMLHttpRequest;
        const open = XHR.prototype.open;
        const send = XHR.prototype.send;
        const setHeader = XHR.prototype.setRequestHeader;
        XHR.prototype.open = function (method, url, ...rest) {
          this.__scraperUrl = url;
          return open.call(this, method, url, ...rest);
        };
        XHR.prototype.setRequestHeader = function (name, value) {
          if (String(name).toLowerCase() === 'authorization') rememberAuth(value);
          return setHeader.call(this, name, value);
        };
        XHR.prototype.send = function (...args) {
          const url = String(this.__scraperUrl || '');
          if (url.includes('/historical/')) {
            this.addEventListener('load', function () {
              try { ingestPayload(JSON.parse(this.responseText), url); } catch (_) {}
            });
          }
          return send.apply(this, args);
        };
        console.log(`[Scraper] listening on ${label}`);
      } catch (_) {}
    }
  
    function eachWindow(fn) {
      fn(window, 'top');
      document.querySelectorAll('iframe').forEach((frame, i) => {
        try { fn(frame.contentWindow, frame.src || `iframe ${i}`); } catch (_) {}
      });
    }
  
    function readVisible() {
      eachWindow((win) => {
        try {
          const items = win.chartWidget?.model?.().mainSeries?.().bars?.()._items;
          const list = Array.isArray(items) ? items : (items ? Object.values(items) : []);
          if (list.length) addCandles(list.filter(Boolean), { token: symbolNow().token, interval: tvInterval() || 'chart' });
        } catch (_) {}
        try {
          const stx = win.stxx || win.stx;
          const data = stx?.masterData || stx?.chart?.dataSet;
          if (data?.length) addCandles(data, { token: symbolNow().token, interval: tvInterval() || 'chart' });
        } catch (_) {}
      });
    }
  
    function discoverUrls() {
      const urls = [];
      eachWindow((win) => {
        try {
          for (const entry of win.performance.getEntriesByType('resource')) {
            if (entry.name.includes('/historical/')) urls.push(entry.name);
          }
        } catch (_) {}
      });
      return [...new Set(urls)];
    }
  
    function openScore(rows, mode) {
      const first = new Map();
      for (const row of rows) {
        if (row.time_source === 'ist_string' || !Number.isFinite(row.epoch_ms)) continue;
        const clock = clockFromEpoch(row.epoch_ms, mode);
        const mins = toMins(clock.time);
        const prev = first.get(clock.date);
        if (prev == null || mins < prev) first.set(clock.date, mins);
      }
      let score = 0;
      for (const mins of first.values()) {
        if (mins === 555 || mins === 540 || mins === 0) score += 2;
        else if (mins === 885) score -= 2;
      }
      return score;
    }
  
    function resolveClock(row, mode) {
      if (row.time_source === 'ist_string' || row.timestamp) return row;
      return { ...row, ...clockFromEpoch(row.epoch_ms, mode) };
    }
  
    function inferInterval(rows, declared) {
      if (declared && declared !== 'chart' && declared !== 'unknown') return declared;
      const diffs = [];
      for (let i = 1; i < rows.length; i++) {
        const d = rows[i].epoch_ms - rows[i - 1].epoch_ms;
        if (d > 0 && d <= 8 * 60 * 60 * 1000) diffs.push(d);
      }
      if (!diffs.length) return 'day';
      diffs.sort((a, b) => a - b);
      const mins = Math.round(diffs[diffs.length >> 1] / 60000);
      if (mins >= 18 * 60) return 'day';
      if (mins === 1) return 'minute';
      return `${mins}minute`;
    }
  
    function enrich(bucket) {
      const raw = [...bucket.rows.values()];
      const mode = openScore(raw, 'ist') >= openScore(raw, 'utc-wall') ? 'ist' : 'utc-wall';
      let rows = raw.map((row) => resolveClock(row, mode)).filter((row) => row.timestamp);
      const interval = inferInterval(rows, bucket.interval);
      const intraday = !['day', 'week', 'month'].includes(interval);
      const dropped = [];
      if (intraday) {
        rows = rows.filter((row) => {
          if (row.time !== '00:00:00') return true;
          dropped.push(row);
          return false;
        });
      }
      const byTs = new Map();
      for (const row of rows) {
        const prev = byTs.get(row.timestamp);
        if (!prev || (row.time_source === 'ist_string' && prev.time_source !== 'ist_string')) byTs.set(row.timestamp, row);
      }
      rows = [...byTs.values()].sort((a, b) => a.epoch_ms - b.epoch_ms);
  
      const tr = rows.map((row, i) => {
        const hl = row.high - row.low;
        if (i === 0) return hl;
        const pc = rows[i - 1].close;
        return Math.max(hl, Math.abs(row.high - pc), Math.abs(row.low - pc));
      });
      const atr = Array(rows.length).fill(null);
      if (rows.length >= 14) {
        let seed = 0;
        for (let i = 0; i < 14; i++) seed += tr[i];
        atr[13] = seed / 14;
        for (let i = 14; i < rows.length; i++) atr[i] = (atr[i - 1] * 13 + tr[i]) / 14;
      }
  
      const dayOrder = [];
      const days = new Map();
      for (const row of rows) {
        if (!days.has(row.date)) {
          days.set(row.date, { high: row.high, low: row.low, close: row.close, volume: 0 });
          dayOrder.push(row.date);
        }
        const day = days.get(row.date);
        day.high = Math.max(day.high, row.high);
        day.low = Math.min(day.low, row.low);
        day.close = row.close;
        day.volume += row.volume;
      }
      const dayTr = dayOrder.map((date, i) => {
        const day = days.get(date);
        const hl = day.high - day.low;
        if (i === 0) return hl;
        const pc = days.get(dayOrder[i - 1]).close;
        return Math.max(hl, Math.abs(day.high - pc), Math.abs(day.low - pc));
      });
      const ewm = Array(dayOrder.length).fill(null);
      if (dayOrder.length) {
        let acc = dayTr[0];
        for (let i = 1; i < dayOrder.length; i++) {
          acc = acc * (13 / 14) + dayTr[i] / 14;
          if (i >= 13) ewm[i] = acc;
        }
      }
      const datrByDate = new Map();
      const avgVolByDate = new Map();
      dayOrder.forEach((date, i) => {
        datrByDate.set(date, i === 0 ? null : ewm[i - 1]);
        if (i < 14) {
          avgVolByDate.set(date, null);
          return;
        }
        let sum = 0;
        for (let j = i - 14; j < i; j++) sum += days.get(dayOrder[j]).volume;
        avgVolByDate.set(date, sum / 14);
      });
  
      const closes = rows.map((row) => row.close);
      function ema(length) {
        const out = Array(closes.length).fill(null);
        if (closes.length < length) return out;
        let sum = 0;
        for (let i = 0; i < length; i++) sum += closes[i];
        let prev = sum / length;
        out[length - 1] = prev;
        const k = 2 / (length + 1);
        for (let i = length; i < closes.length; i++) {
          prev = closes[i] * k + prev * (1 - k);
          out[i] = prev;
        }
        return out;
      }
      const ema20 = ema(20);
      const ema50 = ema(50);
  
      const out = rows.map((row, i) => {
        const range = row.high - row.low;
        const upper = row.high - Math.max(row.open, row.close);
        const lower = Math.min(row.open, row.close) - row.low;
        const body = Math.abs(row.close - row.open);
        const pct = (part) => (range > 0 ? (part / range) * 100 : 0);
        return {
          symbol: bucket.symbol, interval,
          date: row.date, time: row.time, timestamp_ist: row.timestamp,
          open: row.open, high: row.high, low: row.low, close: row.close,
          volume: row.volume,
          upper_wick_pct: pct(upper), lower_wick_pct: pct(lower), body_pct: pct(body),
          tr: tr[i], atr_14: atr[i], datr_14: datrByDate.get(row.date),
          avg_volume_14d: avgVolByDate.get(row.date), ema_20: ema20[i], ema_50: ema50[i],
          time_source: row.time_source,
        };
      });
      return { rows: out, interval, mode, droppedMidnight: dropped.length };
    }
  
    function pickBucket() {
      const list = [...buckets.values()].filter((b) => b.rows.size);
      if (!list.length) return null;
      const official = list.filter((b) => [...b.rows.values()].some((r) => r.time_source === 'ist_string'));
      const pool = official.length ? official : list;
      return pool.sort((a, b) => b.rows.size - a.rows.size)[0];
    }
  
    function round(v, digits) {
      return Number.isFinite(v) ? Number(v.toFixed(digits)) : '';
    }
  
    function download(filename, content, type) {
      const blob = new Blob([content], { type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }
  
    function safeName(bucket, interval) {
      return `${(bucket.symbol || bucket.token || 'kite').replace(/[^A-Z0-9:_-]/gi, '')}_${interval}`;
    }
  
    window.downloadCandlesCSV = function () {
      const bucket = pickBucket();
      if (!bucket) return console.warn('[Scraper] No candles yet.');
      const { rows, interval } = enrich(bucket);
      const header = ['interval', 'date', 'time', 'open', 'high', 'low', 'close', 'volume', 'upper_wick_pct', 'lower_wick_pct', 'body_pct', 'tr', 'atr_14', 'datr_14', 'avg_volume_14d', 'ema_20', 'ema_50'];
      const body = rows.map((r) => [
        r.interval, r.date, r.time,
        r.open, r.high, r.low, r.close, r.volume,
        round(r.upper_wick_pct, 4), round(r.lower_wick_pct, 4), round(r.body_pct, 4),
        round(r.tr, 4), round(r.atr_14, 4), round(r.datr_14, 4), round(r.avg_volume_14d, 2),
        round(r.ema_20, 4), round(r.ema_50, 4),
      ].join(','));
      const name = `${safeName(bucket, interval)}_${rows.length}.csv`;
      download(name, [header.join(','), ...body].join('\n'), 'text/csv');
      console.log(`%c[Scraper] saved ${rows.length} rows → ${name}`, 'color:#00e676;font-weight:bold');
      console.log('[Scraper] sample', rows[0], rows[rows.length - 1]);
    };
  
    window.downloadCandlesJSON = function () {
      const bucket = pickBucket();
      if (!bucket) return console.warn('[Scraper] No candles yet.');
      const { rows, interval } = enrich(bucket);
      const name = `${safeName(bucket, interval)}_${rows.length}.json`;
      download(name, JSON.stringify(rows, null, 2), 'application/json');
      console.log(`%c[Scraper] saved ${rows.length} rows → ${name}`, 'color:#00e676;font-weight:bold');
    };
  
    window.candleStatus = function () {
      const bucket = pickBucket();
      if (!bucket) return console.log('[Scraper] No candles yet. Scroll the chart, or run loadAllHistory().');
      const { rows, interval, mode, droppedMidnight } = enrich(bucket);
      const official = rows.filter((r) => r.time_source === 'ist_string').length;
      console.log(
        `%c[Scraper] ${bucket.symbol || bucket.token} ${interval}\n` +
        `  ${rows.length} candles  ${rows[0].date} ${rows[0].time} → ${rows[rows.length - 1].date} ${rows[rows.length - 1].time}\n` +
        `  exchange timestamps: ${official}/${rows.length}   clock mode: ${mode}\n` +
        `  midnight aggregates removed: ${droppedMidnight}`,
        'color:#42a5f5;font-weight:bold'
      );
    };
  
    window.clearCandles = function () {
      buckets.clear();
      console.log('[Scraper] cleared');
    };
  
    function addDays(date, days) {
      const [y, m, d] = date.split('-').map(Number);
      const dt = new Date(Date.UTC(y, m - 1, d + days));
      return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
    }
  
    function chunkDays(interval) {
      if (interval === 'minute') return 30;
      if (['3minute', '5minute', '10minute', '15minute', '30minute'].includes(interval)) return 90;
      if (interval === '60minute' || interval === '120minute' || interval === '2hour') return 180;
      return 1000;
    }
  
    window.loadAllHistory = async function () {
      let bucket = pickBucket();
      if (!bucket?.lastUrl) {
        const urls = discoverUrls();
        if (urls.length) {
          const url = urls[urls.length - 1];
          const m = url.match(/\/historical\/(\d+)\/([^/?]+)/);
          bucket = bucketFor(m ? m[1] : '', m ? decodeURIComponent(m[2]) : tvInterval());
          bucket.lastUrl = url;
        }
      }
      if (!bucket?.lastUrl) {
        console.warn('[Scraper] Change the chart timeframe once so the history request can be captured, then run loadAllHistory() again.');
        return;
      }
      if (!authHeader) {
        console.warn('[Scraper] No Zerodha enctoken yet. Log in, open the chart so a history request is captured, then run loadAllHistory() again.');
        return;
      }
      const interval = bucket.interval || 'day';
      const span = chunkDays(interval);
      let to = fmtIst(Date.now()).date;
      let empty = 0;
      let requests = 0;
      console.log(`[Scraper] downloading ${bucket.symbol || bucket.token} ${interval}`);
      while (to > '2000-01-01' && empty < 3 && requests < 400) {
        const from = addDays(to, -(span - 1));
        const url = new URL(bucket.lastUrl, location.origin);
        url.searchParams.set('from', `${from < '2000-01-01' ? '2000-01-01' : from} 00:00:00`);
        url.searchParams.set('to', `${to} 23:59:59`);
        const headers = { Accept: 'application/json' };
        if (authHeader) headers.Authorization = authHeader;
        const res = await fetch(url.toString(), { credentials: 'include', headers });
        requests++;
        if (res.status === 429) {
          console.warn('[Scraper] rate limited, waiting 3s');
          await new Promise((r) => setTimeout(r, 3000));
          continue;
        }
        const data = await res.json();
        const candles = data?.data?.candles || [];
        if (!candles.length) empty++;
        else {
          empty = 0;
          addCandles(candles, { token: bucket.token, interval, url: bucket.lastUrl });
        }
        console.log(`[Scraper] ${from} → ${to}: ${candles.length}`);
        to = addDays(from, -1);
        await new Promise((r) => setTimeout(r, 400));
      }
      candleStatus();
    };
  
    eachWindow(patchWindow);
    for (const url of discoverUrls()) {
      const m = url.match(/\/historical\/(\d+)\/([^/?]+)/);
      const b = bucketFor(m ? m[1] : symbolNow().token, m ? decodeURIComponent(m[2]) : tvInterval());
      b.lastUrl = url;
      if (!b.symbol) b.symbol = symbolNow().symbol;
    }
    readVisible();
    setInterval(() => { eachWindow(patchWindow); readVisible(); }, 3000);
  
    console.log(
      '%c[Scraper] ready\n' +
      '  loadAllHistory()      pull full history with Kite timestamps\n' +
      '  candleStatus()        range and timestamp check\n' +
      '  downloadCandlesCSV()  save the columns\n' +
      '  clearCandles()        switch symbol',
      'color:#00e676;font-weight:bold'
    );
  })();
  