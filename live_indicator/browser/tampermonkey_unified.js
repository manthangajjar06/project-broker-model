// ==UserScript==
// @name         Kite Unified Demand Scanner
// @namespace    live-indicator-unified
// @version      0.3.0
// @description  Locked ML-confidence arrows and corrected DBR/RBR zone entries.
// @match        https://kite.zerodha.com/*
// @noframes
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
  'use strict';
  const API_URL = 'http://127.0.0.1:8003/scan';
  const LOCKED = { lock: true, disableSelection: true, disableSave: true };
  let lastKey = null, busy = false, entities = [];
  function chartWindow(win, depth = 5, seen = new Set()) { if (!win || depth < 0 || seen.has(win)) return null; seen.add(win); try { if (win.tradingViewApi && win.chartWidget) return win; for (const node of win.document.querySelectorAll('iframe')) { const hit = chartWindow(node.contentWindow, depth - 1, seen); if (hit) return hit; } } catch (_) {} return null; }
  function read() { const win = chartWindow(window); if (!win) throw Error('Kite chart API unavailable'); const raw = win.chartWidget.model().mainSeries().bars()._items; const candles = (Array.isArray(raw) ? raw : []).map((bar) => ({timestamp:bar.timeMs,open:bar.value[1],high:bar.value[2],low:bar.value[3],close:bar.value[4],volume:bar.value[5] ?? 0})).filter((c) => [c.timestamp,c.open,c.high,c.low,c.close].every(Number.isFinite)); if (candles.length < 3) throw Error('Waiting for valid candles'); const match = document.title.match(/([A-Z0-9&-]+) \(NSE\)/i); return {chart:win.tradingViewApi.activeChart(),symbol:match ? `NSE:${match[1]}` : 'NSE:UNKNOWN',candles}; }
  async function clear() { const old = entities; entities = []; await Promise.all(old.map(async (item) => { try { await item.chart.removeEntity(item.id); } catch (_) {} })); }
  async function draw(chart, zones, signals) { await clear(); for (const zone of zones) { const from = Math.floor(new Date(zone.formed_at).getTime()/1000), to = Math.floor(new Date(zone.draw_until || Date.now()).getTime()/1000), color = zone.status === 'fresh' ? '#00C853' : '#90A4AE'; try { const box = await chart.createMultipointShape([{time:from,price:zone.zone_high},{time:to,price:zone.zone_low}], {shape:'rectangle',...LOCKED,overrides:{linecolor:color,backgroundColor:color,transparency:85,linewidth:2}}); entities.push({chart,id:box}); const price = zone.entry.final_entry ?? zone.entry.base_entry; const entry = await chart.createMultipointShape([{time:from,price},{time:to,price}], {shape:'trend_line',...LOCKED,overrides:{linecolor:'#2196F3',linewidth:2}}); entities.push({chart,id:entry}); } catch (error) { console.warn('[Unified Scanner] Zone drawing failed', error); } }
    for (const signal of signals) { const accepted = signal.prediction === 'accepted', confidence = accepted ? signal.acceptance_confidence_pct : signal.rejection_confidence_pct; try { const id = await chart.createShape({time:Math.floor(new Date(signal.time).getTime()/1000),price:accepted ? signal.zone_low : signal.zone_high}, {shape:accepted?'arrow_up':'arrow_down',text:`${signal.type} ${accepted?'ACCEPTED':'REJECTED'} ${confidence}%`,...LOCKED,overrides:{color:accepted?'#00E676':'#FF1744',fontsize:12}}); entities.push({chart,id}); } catch (error) { console.warn('[Unified Scanner] Signal drawing failed', error); } }
  }
  async function sync() { if (busy) return; let data; try { data = read(); } catch (_) { return; } const last = data.candles[data.candles.length - 1], key = `${data.symbol}:${data.candles.length}:${last.timestamp}:${last.close}`; if (key === lastKey) return; busy = true; try { const response = await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbol:data.symbol,candles:data.candles})}); if (!response.ok) throw Error(await response.text()); const result = await response.json(); await draw(data.chart,result.zones,result.signals); lastKey = key; console.info('[Unified Scanner]', {zones:result.zones.length,signals:result.signals.length}); } catch (error) { console.warn('[Unified Scanner] API on port 8003 unavailable',error); } finally { busy = false; } }
  setInterval(sync, 3000); sync();
}());
