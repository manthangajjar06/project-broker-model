// ==UserScript==
// @name         Kite Unified Demand Scanner (fixed)
// @namespace    live-indicator-unified-fixed
// @version      1.4.0
// @description  Closed-candle DBR/RBR zones with linked ML confidence arrows for accepted, rejected, and uncertain zones.
// @match        https://kite.zerodha.com/*
// @noframes
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';
  const W = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
  const API_URL = 'http://127.0.0.1:8003/scan';
  const POLL_MS = 2500;
  const LOCKED = { lock: true, disableSelection: true, disableSave: true };
  const COLORS = { fresh: '#00C853', worked: '#FFB300', invalidated: '#90A4AE', entry: '#2196F3' };
  const MARKER_RENDER_VERSION = 2;
  const state = { key: null, chart: null, visuals: new Map(), arrows: new Map(), busy: false };
  if (W.__liveIndicatorUnifiedFixed) return;
  W.__liveIndicatorUnifiedFixed = true;

  function findChart(win, depth = 5, seen = new Set()) {
    if (!win || depth < 0 || seen.has(win)) return null;
    seen.add(win);
    try {
      if (win.tradingViewApi && win.chartWidget) return win;
      for (const iframe of win.document.querySelectorAll('iframe')) {
        const found = findChart(iframe.contentWindow, depth - 1, seen);
        if (found) return found;
      }
    } catch (_) {}
    return null;
  }

  function readChart() {
    const win = findChart(W);
    if (!win) throw Error('Kite chart API unavailable');
    const items = win.chartWidget.model().mainSeries().bars()._items;
    const candles = (Array.isArray(items) ? items : []).map((bar) => ({
      timestamp: bar.timeMs, open: bar.value[1], high: bar.value[2], low: bar.value[3], close: bar.value[4], volume: bar.value[5] ?? 0,
    })).filter((c) => [c.timestamp, c.open, c.high, c.low, c.close].every(Number.isFinite));
    if (candles.length < 3) throw Error('Waiting for valid chart candles');
    const title = W.document.title.match(/([A-Z0-9&-]+) \(NSE\)/i);
    const chart = win.tradingViewApi.activeChart();
    const resolution = chart.resolution?.() ?? 'unknown';
    const last = candles[candles.length - 1];
    return { chart, candles, symbol: title ? `NSE:${title[1]}` : 'NSE:UNKNOWN', key: `${title?.[1] ?? 'UNKNOWN'}|${resolution}|${candles.length}|${last.timestamp}` };
  }

  function request(payload) {
    return new Promise((resolve, reject) => GM_xmlhttpRequest({
      method: 'POST', url: API_URL, headers: { 'Content-Type': 'application/json' }, data: JSON.stringify(payload), timeout: 20000,
      onload: (response) => { try { response.status < 300 ? resolve(JSON.parse(response.responseText)) : reject(Error(`HTTP ${response.status}: ${response.responseText}`)); } catch (error) { reject(error); } },
      onerror: () => reject(Error('API unreachable')), ontimeout: () => reject(Error('API timeout')),
    }));
  }

  async function remove(chart, ids) { await Promise.all(ids.map(async (id) => { try { await chart.removeEntity(id); } catch (_) {} })); }
  function zoneFingerprint(zone, meta) { return JSON.stringify([zone.status, zone.draw_until, zone.zone_low, zone.zone_high, zone.entry.final_entry, meta.last_closed_at]); }
  function arrowFingerprint(zone) { return JSON.stringify([MARKER_RENDER_VERSION, zone.status, zone.ml, zone.formed_at, zone.zone_low, zone.zone_high]); }

  async function drawVisual(chart, zone, meta) {
    const from = Math.floor(new Date(zone.formed_at).getTime() / 1000);
    const to = Math.floor(new Date(zone.draw_until || meta.last_closed_at).getTime() / 1000);
    const color = COLORS[zone.status] || COLORS.invalidated;
    const box = await chart.createMultipointShape([{ time: from, price: zone.zone_high }, { time: to, price: zone.zone_low }], { shape: 'rectangle', ...LOCKED, overrides: { linecolor: color, backgroundColor: color, transparency: 85, linewidth: 2 } });
    const entry = await chart.createMultipointShape([{ time: from, price: zone.entry.final_entry }, { time: to, price: zone.entry.final_entry }], { shape: 'trend_line', ...LOCKED, overrides: { linecolor: zone.entry.warning ? '#FF9800' : COLORS.entry, linewidth: 2 } });
    return [box, entry];
  }

  async function drawArrow(chart, zone) {
    const time = Math.floor(new Date(zone.formed_at).getTime() / 1000);
    // The lifecycle state has priority on the chart. A fresh zone is pending
    // until price revisits it, so render one unambiguous yellow marker instead
    // of a green/red ML marker. The ML decision remains visible in its text.
    if (zone.status === 'fresh') {
      const mlText = zone.ml
        ? ` | ML ${zone.ml.label.toUpperCase()} ${Math.round(Number(zone.ml.p_accept) * 100)}%`
        : '';
      const pendingId = await chart.createShape(
        { time, price: zone.zone_low },
        { shape: 'arrow_up', text: `${zone.pattern_type} PENDING / UNTOUCHED${mlText}`, ...LOCKED,
          overrides: { color: '#FFD600', fontsize: 12 } },
      );
      return [pendingId];
    }

    // Worked and invalidated zones retain their independent ML classification.
    if (!zone.ml) return [];
    const label = zone.ml.label;
    const acceptedPct = Math.round(Number(zone.ml.p_accept) * 100);
    const rejected = label === 'rejected';
    const text = rejected
      ? `${zone.pattern_type} ${zone.leg_out_mode} REJECTED ${100 - acceptedPct}%`
      : label === 'uncertain'
        ? `${zone.pattern_type} ${zone.leg_out_mode} UNSURE p=${acceptedPct}%`
        : `${zone.pattern_type} ${zone.leg_out_mode} ACCEPTED ${acceptedPct}%`;
    const mlId = await chart.createShape(
      { time, price: rejected ? zone.zone_high : zone.zone_low },
      { shape: rejected ? 'arrow_down' : 'arrow_up', text, ...LOCKED,
        overrides: { color: rejected ? '#FF1744' : label === 'accepted' ? '#00E676' : '#FFB300', fontsize: 12 } },
    );
    return [mlId];
  }

  async function apply(chart, zones, meta) {
    if (state.chart && state.chart !== chart) {
      for (const rec of state.visuals.values()) await remove(state.chart, rec.ids);
      for (const rec of state.arrows.values()) await remove(state.chart, rec.ids);
      state.visuals.clear(); state.arrows.clear();
    }
    state.chart = chart;
    const visuals = new Map();
    for (const zone of zones) if (!visuals.has(zone.visual_id)) visuals.set(zone.visual_id, zone);
    for (const [id, rec] of [...state.visuals]) { const zone = visuals.get(id); if (!zone || rec.fp !== zoneFingerprint(zone, meta)) { await remove(chart, rec.ids); state.visuals.delete(id); } }
    for (const [id, zone] of visuals) if (!state.visuals.has(id)) { try { state.visuals.set(id, { fp: zoneFingerprint(zone, meta), ids: await drawVisual(chart, zone, meta) }); } catch (error) { console.warn('[Unified Scanner] Zone drawing failed', id, error); } }
    // A physical zone can yield multiple detector variants (for example,
    // SINGLE and SUPER). `visuals` has already selected one record per
    // visual_id, so use the same identity for its marker to prevent labels
    // from being drawn on top of one another.
    const arrowZones = visuals;
    for (const [id, rec] of [...state.arrows]) { const zone = arrowZones.get(id); if (!zone || rec.fp !== arrowFingerprint(zone)) { await remove(chart, rec.ids); state.arrows.delete(id); } }
    for (const [id, zone] of arrowZones) if (!state.arrows.has(id)) { try { state.arrows.set(id, { fp: arrowFingerprint(zone), ids: await drawArrow(chart, zone) }); } catch (error) { console.warn('[Unified Scanner] Arrow drawing failed', id, error); } }
  }

  async function sync() {
    if (state.busy || W.document.hidden) return;
    let data; try { data = readChart(); } catch (_) { return; }
    if (state.key === data.key) return;
    state.busy = true;
    try {
      const response = await request({ symbol: data.symbol, candles: data.candles });
      await apply(data.chart, response.zones || [], response.meta || {});
      state.key = data.key;
      console.info('[Unified Scanner]', { zones: response.zones?.length ?? 0, dropped: response.meta?.dropped_bars ?? 0 });
    } catch (error) { console.warn('[Unified Scanner] Scan failed', error); }
    finally { state.busy = false; }
  }
  W.document.addEventListener('visibilitychange', () => { if (!W.document.hidden) { state.key = null; sync(); } });
  setInterval(sync, POLL_MS); sync();
}());
